#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
reconciliation4_rebuilt.py
A reconstructed reconciliation utility based on the provided screenshots.
- Validations for files/columns/queries/counts
- Comparison using mapping (Source, Target, PrimaryKey)
- Hash-key based union/intersection to find extras
- Optional primary-key scan with CSV exports for source-only / target-only
- Optional record-linkage exact comparisons across mapped columns
- Excel detail report with conditional formatting
- Batch runner driven by a JSON config (-f/--config)
This is a faithful-but-not-identical reconstruction so you can run/iterate now.
Fill in any TODOs that need your environment specifics.
"""

import os
import sys
import json
import time
import argparse
import logging
import warnings
from datetime import datetime
import hashlib

import pandas as pd
import numpy as np

# Optional dependencies seen in screenshots
try:
    import duckdb as db
except Exception:
    db = None

try:
    import redshift_connector
except Exception:
    redshift_connector = None

try:
    import recordlinkage
except Exception:
    recordlinkage = None

warnings.filterwarnings("ignore")


# -----------------------------------------------------------------------------
# Helper: validations
# -----------------------------------------------------------------------------
class Validations:
    def __init__(self):
        pass

    def checkFilePath(self, path, logger):
        logger.info("Checking the path exists or not")
        if not os.path.exists(path):
            raise FileNotFoundError(f"Specified {path} path doesn't exist.")
        logger.info("Done")

    def missing_rows_validations(self, df, logger):
        """
        Validate mapping file for missing Source/Target values on any row.
        Expects columns: ['Source','Target'].
        """
        logger.info("Checking the Missing values in mapping file")
        missing_rows = df[df[['Source', 'Target']].isnull().any(axis=1)]
        if not missing_rows.empty:
            raise Exception(
                "Mapping file has rows with NULLs in Source/Target: "
                + missing_rows.to_json(orient='records')
            )
        logger.info("No null values in the mapping file")

    def primary_key_validations(self, df, logger):
        """
        Ensure PrimaryKey column exists and that at least one row is marked 'Y'.
        """
        logger.info("Checking PrimaryKey availability in the mapping file")
        if 'PrimaryKey' not in df.columns:
            raise Exception("PrimaryKey column not present in mapping file")
        if (df['PrimaryKey'].astype(str).str.upper() == 'Y').sum() == 0:
            raise Exception("Primary Key not selected in mapping")
        logger.info("Primary key(s) are available in the file")

    def column_validations(self, columns, list_, logger):
        """
        Confirm all mapped columns exist in dataset columns.
        columns: iterable of actual column names
        list_:   iterable of mapped names to verify
        """
        logger.info(
            f"Checking mapped columns {list_} are present in dataset columns"
        )
        dataset_cols_lower = set(map(str.lower, columns))
        mismatch = [c for c in list_ if str(c).lower() not in dataset_cols_lower]
        if mismatch:
            raise Exception(f"Columns {mismatch} in mapping are not present in dataset")
        logger.info("Column validations are done")

    def query_validations(self, source_query, target_query, logger):
        logger.info("Checking the Query validations")
        if not str(source_query).strip() or not str(target_query).strip():
            raise Exception("One of the given queries is empty")
        logger.info("Query checks are completed")
        return True

    def count_validations(self, srcDF, trgtDF, logger):
        """Row count check on both dataframes (does not force equality)."""
        logger.info("Checking the row count on both the dataframes")
        src_cnt = len(srcDF)
        trg_cnt = len(trgtDF)
        logger.info("No. of records present in source dataframe is : %s", src_cnt)
        logger.info("No. of records present in target dataframe is : %s", trg_cnt)
        if src_cnt == 0 or trg_cnt == 0:
            raise Exception("Source/Target Datasets are empty")
        if src_cnt != trg_cnt:
            logger.info(
                "Mismatch between Source rows (%s) and Target rows (%s)",
                src_cnt, trg_cnt
            )
        logger.info("Done")
        return src_cnt, trg_cnt


# -----------------------------------------------------------------------------
# Core reconciliation
# -----------------------------------------------------------------------------
class Reconciliation(Validations):
    def __init__(self, base_path="."):
        super().__init__()
        self.path = os.path.abspath(base_path)
        self.batch_name = "batch"
        self.curr_time = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.count_dict = {}
        self.mismatch_count_df = pd.DataFrame(columns=["Table", "Mismatch_Group_Count"])
        self.unique_count_df = pd.DataFrame(columns=["Table", "Source_Only", "Target_Only", "Exists_Both"])
        self.writer = None
        self.source_connection = None
        self.target_connection = None

    # ------------ utility: hash over a row (mapped columns in order) ----------
    @staticmethod
    def generateHash(x):
        return hashlib.sha256("_".join(map(str, x)).encode()).hexdigest()

    # ------------ data fetch for DB cursors -----------------------------------
    def getData(self, query, cursor):
        try:
            cursor.execute(query)
            # duckdb cursor has .fetch_df(); redshift_connector uses pandas.read_sql
            if hasattr(cursor, "fetch_df"):
                return cursor.fetch_df()
            else:
                import pandas as _pd
                return _pd.read_sql(query, cursor.connection)
        except Exception as e:
            raise Exception("Not able to connect to data source!") from e

    # ------------ excel detail report with formats ----------------------------
    def reportGenerator(self, df, table_name):
        """
        Writes an XLSX detail report under <batch>/DetailReport/DetailReport_<ts>.xlsx
        and applies several conditional formats (simplified).
        """
        detail_dir = os.path.join(self.path, self.batch_name, "DetailReport")
        os.makedirs(detail_dir, exist_ok=True)
        out_path = os.path.join(detail_dir, f"DetailReport_{self.curr_time}.xlsx")

        # create writer lazily once to place multiple sheets
        if self.writer is None:
            self.writer = pd.ExcelWriter(out_path, engine="xlsxwriter")

        df.to_excel(self.writer, sheet_name=table_name, index=False)

        workbook = self.writer.book
        worksheet = self.writer.sheets[table_name]

        # Formats (colors inferred from screenshots)
        fmt_bad   = workbook.add_format({'bg_color': '#FF0000'})  # red
        fmt_info  = workbook.add_format({'bg_color': '#0066FF'})  # blue
        fmt_grey  = workbook.add_format({'bg_color': '#808080'})  # grey
        fmt_good  = workbook.add_format({'bg_color': '#009900'})  # green
        fmt_warn1 = workbook.add_format({'bg_color': '#FF9933'})  # orange
        fmt_warn2 = workbook.add_format({'bg_color': '#CCCC33'})  # yellow

        rows = len(df)
        cols = len(df.columns)
        # Example conditional formats (simplified); adapt as you wish.
        worksheet.conditional_format(0, 0, rows, cols-1,
                                     {'type': 'cell', 'criteria': '==', 'value': '"False"', 'format': fmt_bad})
        worksheet.conditional_format(0, 0, rows, cols-1,
                                     {'type': 'cell', 'criteria': '==', 'value': '"True"', 'format': fmt_good})

    # ------------ comparison logic -------------------------------------------
    def comparison(self, df1, df2, mapConfDF, batch_name, table_name, ispkscan=False, out_path=None, logger=None,
                   max_mismatch_records=100, max_match_records=100):
        """
        Compare df1 (source) vs df2 (target) using mapping:
        - Build 'hashkey' over mapped columns / PKs
        - Compute union / intersection / uncommon sets
        - For pk-scan, export source_only/target_only CSVs
        - Use recordlinkage exact comparisons (if available) for detail mismatch view
        """
        out_path = out_path or os.path.join(self.path, self.batch_name)
        os.makedirs(out_path, exist_ok=True)

        map_source_columns = mapConfDF['Source'].tolist()
        map_target_columns = mapConfDF['Target'].tolist()
        map_source_pks = mapConfDF.loc[mapConfDF['PrimaryKey'].astype(str).str.upper() == "Y", 'Source'].tolist()
        map_target_pks = mapConfDF.loc[mapConfDF['PrimaryKey'].astype(str).str.upper() == "Y", 'Target'].tolist()

        # Hash over the mapped columns
        df1 = df1.copy()
        df2 = df2.copy()
        df1['hashkey'] = df1[map_source_columns].apply(self.generateHash, axis=1)
        df2['hashkey'] = df2[map_target_columns].apply(self.generateHash, axis=1)
        if logger: logger.info("hash key built for both dataframes")

        union = pd.Series(pd.unique(pd.concat([df1.hashkey, df2.hashkey])))
        intersect = pd.Series(np.intersect1d(df1.hashkey, df2.hashkey))
        notcommonseries = union[~union.isin(intersect)]

        if len(notcommonseries) == 0:
            # all matched on mapped columns
            self.count_dict.setdefault(table_name, {})
            self.count_dict[table_name].update({
                "Source_Only": 0, "Target_Only": 0, "Exists_Both": len(intersect)
            })
            return "Same"

        if ispkscan:
            # PK scan branch – identify missing keys on each side
            source = df1[df1.hashkey.isin(notcommonseries)]
            target = df2[df2.hashkey.isin(notcommonseries)]

            source_only = source[~source['hashkey'].isin(df2['hashkey'])].drop(columns=['hashkey'], errors='ignore')
            target_only = target[~target['hashkey'].isin(df1['hashkey'])].drop(columns=['hashkey'], errors='ignore')

            src_dir = os.path.join(out_path, "source_missing")
            trg_dir = os.path.join(out_path, "target_missing")
            os.makedirs(src_dir, exist_ok=True)
            os.makedirs(trg_dir, exist_ok=True)

            if len(source_only):
                source_only.to_csv(os.path.join(src_dir, f"{batch_name}_{table_name}_{self.curr_time}.csv"), index=False)
            if len(target_only):
                target_only.to_csv(os.path.join(trg_dir, f"{batch_name}_{table_name}_{self.curr_time}.csv"), index=False)

            if logger:
                logger.info("Source file contains %s extra rows", source_only.shape[0])
                logger.info("Target file contains %s extra rows", target_only.shape[0])

            self.count_dict.setdefault(table_name, {})
            self.count_dict[table_name].update({
                "Source_Only": int(source_only.shape[0]),
                "Target_Only": int(target_only.shape[0]),
                "Exists_Both": int(len(intersect))
            })

        # Record-linkage exact compare to build mismatch groups (optional)
        if recordlinkage is not None and len(map_source_columns) > 0:
            # Build index – prefer blocking on PKs if available and unique
            try:
                idx = recordlinkage.Index()
                if map_source_pks and map_target_pks and len(map_source_pks) == len(map_target_pks):
                    # heuristic: if PKs exist, try full index on them by setting them as index
                    pairs = idx.full().index(df1.set_index(map_source_pks, drop=False),
                                             df2.set_index(map_target_pks, drop=False))
                else:
                    pairs = idx.full().index(df1, df2)

                comp = recordlinkage.Compare()
                for s_col, t_col in zip(map_source_columns, map_target_columns):
                    comp.exact(s_col, t_col, label=f"eq::{s_col}->{t_col}")

                comp_vec = comp.compute(pairs,
                                        df1.replace(np.nan, "NULL"),
                                        df2.replace(np.nan, "NULL"))
                mismatch_groups = (comp_vec.sum(axis=1) < comp_vec.shape[1])
                mismatch_count = int(mismatch_groups.sum())
            except Exception:
                comp_vec = pd.DataFrame()
                mismatch_count = 0
        else:
            comp_vec = pd.DataFrame()
            mismatch_count = 0

        self.mismatch_count_df = pd.concat(
            [self.mismatch_count_df,
             pd.DataFrame([{"Table": table_name, "Mismatch_Group_Count": mismatch_count}])],
            ignore_index=True
        )

        # Prepare a compact detail sheet including some examples of matches/mismatches
        try:
            if not comp_vec.empty:
                # take sample rows for report
                level0 = getattr(comp_vec.index, "get_level_values", lambda _: pd.Index([]))
                if len(level0(0)) == 0:
                    # Fallback: reconstruct approximate keys row numbers
                    x_id = comp_vec.index
                    left_ids = [i[0] if isinstance(i, tuple) else i for i in x_id]
                    right_ids = [i[1] if isinstance(i, tuple) else i for i in x_id]
                else:
                    left_ids = level0(0)
                    right_ids = level0(1)

                # Pull sample records
                take_mismatch = min(max_mismatch_records, mismatch_count) if mismatch_count else 0
                if take_mismatch:
                    left_df = df1.iloc[list(map(int, left_ids[:take_mismatch]))][map_source_columns]
                    right_df = df2.iloc[list(map(int, right_ids[:take_mismatch]))][map_target_columns]
                    left_df["Disposition"] = "Source Record"
                    right_df["Disposition"] = "Target Record"
                    # unify columns for a single sheet
                    merged_cols = list(dict.fromkeys(map_source_columns + map_target_columns + ["Disposition"]))
                    out_df = pd.concat([left_df, right_df], ignore_index=True)[merged_cols]
                    self.reportGenerator(out_df, f"{table_name}_detail")
        except Exception:
            # non-fatal
            pass

        return "Different"

    # ------------------------- connections (Redshift) -------------------------
    @staticmethod
    def getCursor(connections):
        """
        Build a redshift_connector cursor from a comma-separated string:
        "host,port,database" – the script will prompt for user/password.
        """
        if redshift_connector is None:
            raise RuntimeError("redshift_connector not installed")
        parts = [p.strip() for p in str(connections).split(",")]
        if len(parts) < 3:
            raise ValueError("connections must be 'host,port,database'")
        host = parts[0]
        port = int(parts[1])
        database = parts[2]
        user = input("Please Enter User Name : ")
        password = input("Please Enter Password : ")
        conn = redshift_connector.connect(
            host=host, port=port, database=database, user=user, password=password
        )
        return conn, conn.cursor()

    # ---------------------------- per-batch run -------------------------------
    def reconcile(self, batch):
        """
        One batch entry from config: { mapping_file_path, source_query, target_query, table_name }
        """
        mapping_file_path = batch["mapping_file_path"]
        source_query = batch["source_query"]
        target_query = batch["target_query"]
        table_name = batch["table_name"]

        # logger for this table
        filename = f"log_{table_name}_{self.curr_time}"
        logger = logging.getLogger(filename)
        logger.setLevel(logging.INFO)
        handler = logging.FileHandler(os.path.join(self.path, self.batch_name, "logs", f"{filename}.log"))
        handler.setLevel(logging.INFO)
        formatter = logging.Formatter('%(name)s:%(levelname)s:%(asctime)s:%(message)s')
        handler.setFormatter(formatter)
        if not logger.handlers:
            logger.addHandler(handler)

        logger.info(
            "Given configurations are: mapping_file_path=%s | source_query=%s | target_query=%s",
            mapping_file_path, source_query, target_query
        )

        # Path & mapping
        self.checkFilePath(mapping_file_path, logger)
        mapConfDF = pd.read_csv(mapping_file_path)
        mapConfDF.fillna(np.NaN, inplace=True)
        mapConfDF.replace('', np.NaN, inplace=True)

        # Validations
        self.missing_rows_validations(mapConfDF, logger)
        self.primary_key_validations(mapConfDF, logger)

        # Data fetch
        # Local CSV example from screenshots (change to DB mode if required)
        # srcDF = self.getData(source_query, source_cursor)
        # trgtDF = self.getData(target_query, target_cursor)
        srcDF = pd.read_csv("titanic_train_source.csv", dtype=str) if source_query == "__LOCAL_DEMO__" else pd.read_csv(source_query) if os.path.isfile(source_query) else pd.DataFrame()
        trgtDF = pd.read_csv("titanic_train_target.csv", dtype=str) if target_query == "__LOCAL_DEMO__" else pd.read_csv(target_query) if os.path.isfile(target_query) else pd.DataFrame()

        # Column checks
        self.column_validations(srcDF.columns, mapConfDF["Source"].tolist(), logger)
        self.column_validations(trgtDF.columns, mapConfDF["Target"].tolist(), logger)

        # Count validations & store
        src_cnt, trg_cnt = self.count_validations(srcDF, trgtDF, logger)
        self.count_dict.setdefault(table_name, {})
        self.count_dict[table_name].update({
            "Table": table_name,
            "Source_Count": src_cnt,
            "Target_Count": trg_cnt,
            "Source_Query": source_query,
            "Target_Query": target_query
        })

        # PK scan
        logger.info("Checking missing primary key(s) between the datasets")
        _ = self.comparison(
            srcDF[list(mapConfDF.loc[mapConfDF['PrimaryKey'].astype(str).str.upper() == "Y", 'Source'])],
            trgtDF[list(mapConfDF.loc[mapConfDF['PrimaryKey'].astype(str).str.upper() == "Y", 'Target'])],
            mapConfDF[mapConfDF['PrimaryKey'].astype(str).str.upper() == "Y"],
            batch_name=self.batch_name, table_name=table_name, ispkscan=True,
            out_path=os.path.join(self.path, self.batch_name), logger=logger
        )
        logger.info("Primary key(s) on both the datasets processed")

        # Full scan
        logger.info("Doing the full scan on both the datasets")
        result = self.comparison(srcDF, trgtDF, mapConfDF, batch_name=self.batch_name,
                                 table_name=table_name, ispkscan=False,
                                 out_path=os.path.join(self.path, self.batch_name), logger=logger)

        if result == "Same":
            logger.info("Both the datasets are same")
        else:
            logger.info("Both the datasets are not same")

    # ------------------------------- main runner ------------------------------
    def main(self, config):
        """
        Config JSON format:
        {
          "source_connections": "host,port,database",  // optional if DB
          "target_connections": "host,port,database",  // optional if DB
          "batch_name": "my_batch",
          "batch_files": [
             {
               "mapping_file_path": "mapping.csv",
               "source_query": "source.csv",
               "target_query": "target.csv",
               "table_name": "table1"
             }
          ],
          "max_mismatch_records": 100,
          "max_match_records": 100
        }
        """
        try:
            source_connections = config.get("source_connections", "")
            target_connections = config.get("target_connections", "")
            self.batch_name = config.get("batch_name", "batch")
            batch_files = config.get("batch_files", [])
            self.max_mismatch_records = int(config.get("max_mismatch_records", 100))
            self.max_match_records = int(config.get("max_match_records", 100))

            # directories
            base = os.path.join(self.path, self.batch_name)
            os.makedirs(base, exist_ok=True)
            os.makedirs(os.path.join(base, "logs"), exist_ok=True)
            os.makedirs(os.path.join(base, "source_missing"), exist_ok=True)
            os.makedirs(os.path.join(base, "target_missing"), exist_ok=True)
            os.makedirs(os.path.join(base, "DetailReport"), exist_ok=True)

            # create a placeholder workbook for Count sheet (closed in finally)
            detail_path = os.path.join(base, "DetailReport", f"DetailReport_{self.curr_time}.xlsx")
            self.writer = pd.ExcelWriter(detail_path, engine="xlsxwriter")

            # Run all batches
            for batch in batch_files:
                self.reconcile(batch)

            return "Success"

        except Exception as error:
            t, v, tb = sys.exc_info()
            print(t, "->", v)
            raise

        finally:
            # Write the "Count" sheet combining totals
            try:
                count_df = pd.DataFrame.from_dict(self.count_dict, orient="index")
                count_df.insert(0, "Table", count_df.index)
                count_df = count_df.reset_index(drop=True)
                # Append mismatch_count_df if available
                out_df = pd.merge(count_df, self.mismatch_count_df, on="Table", how="left")
                out_df.to_excel(self.writer, sheet_name="Count", index=False)
            except Exception:
                pass

            # Close writer
            try:
                if self.writer is not None:
                    self.writer.close()
            except Exception:
                pass

            # No DB connections opened in this reconstruction; keep stubs
            try:
                if self.source_connection: self.source_connection.close()
                if self.target_connection: self.target_connection.close()
            except Exception:
                pass

            # Attempt to remove empty subfolders created for cleanliness
            for sub in ("source_missing", "target_missing", "logs"):
                folder = os.path.join(self.path, self.batch_name, sub)
                try:
                    if os.path.isdir(folder) and len(os.listdir(folder)) == 0:
                        os.rmdir(folder)
                except Exception:
                    pass
            # Remove batch folder if everything was empty (unlikely after reports)
            try:
                batch_folder = os.path.join(self.path, self.batch_name)
                if len(os.listdir(batch_folder)) == 0:
                    os.rmdir(batch_folder)
            except Exception:
                pass


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------
def parse_args():
    ap = argparse.ArgumentParser(description="Reconciliation tool (rebuilt)")
    ap.add_argument("-f", "--config", type=str, required=True,
                    help="Path to the config JSON file")
    ap.add_argument("--base-path", type=str, default=".",
                    help="Base path for outputs (default: current directory)")
    return ap.parse_args()


def load_config(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def run():
    args = parse_args()
    cfg = load_config(args.config)
    recon = Reconciliation(base_path=args.base_path)
    out = recon.main(cfg)
    print(out)


if __name__ == "__main__":
    run()
