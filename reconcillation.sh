#!/usr/bin/env bash
set -euo pipefail

# Reconcile two delimited files (CSV/TSV/pipe) and generate reports:
#   - <prefix>_missing_in_target.csv
#   - <prefix>_extra_in_target.csv
#   - <prefix>_mismatched_values.csv
#   - <prefix>_duplicates_source.csv
#   - <prefix>_duplicates_target.csv
#   - <prefix>_schema_diff.txt
#   - <prefix>_summary.txt
#   - <prefix>_overview.xml   (Excel-friendly file with 2 sheets: Schema_Diff, Summary)
#
# Usage (tolerance and prefix are optional):
#   ./reconcile.sh -s source.csv -t target.csv -k "id" [-d ","|$'\t'|"|"] [-H 1|0]
#
# Options:
#   -s   Source file (required)
#   -t   Target file (required)
#   -k   Key columns (comma-separated). Header names if -H 1, or 1-based indexes if -H 0.
#   -d   Delimiter. Default ",". For TAB, use $'\t'
#   -H   Header present? 1=yes (default), 0=no
#   -T   Numeric tolerance (default 0.0). OPTIONAL; omit if you don’t need it.
#   -p   Report file prefix (default "reconcile"). OPTIONAL; omit to use default.

usage() {
  grep '^#' "$0" | sed 's/^# \{0,1\}//'
}

SRC=""; TGT=""; KEYS=""
DELIM=","
HAS_HEADER=1
TOL="0.0"          # <- optional; you can omit -T
PREFIX="reconcile" # <- optional; you can omit -p

while getopts ":s:t:k:d:H:T:p:h" opt; do
  case $opt in
    s) SRC="$OPTARG" ;;
    t) TGT="$OPTARG" ;;
    k) KEYS="$OPTARG" ;;
    d) DELIM="$OPTARG" ;;
    H) HAS_HEADER="$OPTARG" ;;
    T) TOL="$OPTARG" ;;   # optional
    p) PREFIX="$OPTARG" ;;# optional
    h) usage; exit 0 ;;
    \?) echo "Invalid option: -$OPTARG" >&2; usage; exit 2 ;;
    :)  echo "Option -$OPTARG requires an argument." >&2; usage; exit 2 ;;
  esac
done

if [[ -z "$SRC" || -z "$TGT" || -z "$KEYS" ]]; then
  echo "Error: -s, -t, and -k are required." >&2
  usage
  exit 2
fi
if [[ ! -f "$SRC" ]]; then echo "Error: source file '$SRC' not found." >&2; exit 2; fi
if [[ ! -f "$TGT" ]]; then echo "Error: target file '$TGT' not found." >&2; exit 2; fi

# Clean old reports with same prefix
rm -f "${PREFIX}_missing_in_target.csv" \
      "${PREFIX}_extra_in_target.csv" \
      "${PREFIX}_mismatched_values.csv" \
      "${PREFIX}_duplicates_source.csv" \
      "${PREFIX}_duplicates_target.csv" \
      "${PREFIX}_schema_diff.txt" \
      "${PREFIX}_summary.txt" \
      "${PREFIX}_overview.xml" || true

awk -v FS="$DELIM" -v OFS="," \
    -v src_file="$SRC" -v tgt_file="$TGT" \
    -v key_spec="$KEYS" -v has_header="$HAS_HEADER" -v tol="$TOL" \
    -v out_missing="${PREFIX}_missing_in_target.csv" \
    -v out_extra="${PREFIX}_extra_in_target.csv" \
    -v out_mismatch="${PREFIX}_mismatched_values.csv" \
    -v out_dups_src="${PREFIX}_duplicates_source.csv" \
    -v out_dups_tgt="${PREFIX}_duplicates_target.csv" \
    -v out_schema="${PREFIX}_schema_diff.txt" \
    -v out_summary="${PREFIX}_summary.txt" '
function ltrim(s){ sub(/^[ \t\r\n]+/, "", s); return s }
function rtrim(s){ sub(/[ \t\r\n]+$/, "", s); return s }
function trim(s){ return rtrim(ltrim(s)) }
function isnum(x){ return (x ~ /^[-+]?[0-9]*\.?[0-9]+([eE][-+]?[0-9]+)?$/) }
function abs(x){ return x<0?-x:x }

function split_list(spec, arr){ gsub(/[ \t]+/, "", spec); return split(spec, arr, / *, */) }

function build_header_index(harr, n, map,  i) { for (i=1;i<=n;i++) map[tolower(harr[i])] = i }

function parse_key_indexes(spec, use_header, hdr_map, kidx,   tmp, n, i, v, idx) {
  n = split_list(spec, tmp)
  for (i=1;i<=n;i++) {
    v = tmp[i]
    if (use_header) {
      idx = hdr_map[tolower(v)]
      if (!idx) { printf("ERROR: Key column name \"%s\" not found in header.\n", v) > "/dev/stderr"; exit 3 }
      kidx[i] = idx
    } else {
      if (v !~ /^[0-9]+$/) { printf("ERROR: Non-numeric key \"%s\" with -H 0.\n", v) > "/dev/stderr"; exit 3 }
      kidx[i] = v + 0
    }
  }
  return n
}

function make_key(kidx, nk,  i, s, part) {
  s = ""
  for (i=1;i<=nk;i++) {
    part = trim($(kidx[i]))
    s = (i==1 ? part : s "|" part)
  }
  return s
}

function csv_safe(s,  t) {
  t = s
  if (t ~ /[",\r\n]/) { gsub(/"/, "\"\"", t); t = "\"" t "\"" }
  return t
}

function equal_with_tol(a, b) {
  a = trim(a); b = trim(b)
  if (isnum(a) && isnum(b)) return abs(a - b) <= tol + 0.0
  return a == b
}

FNR==1 && NR==1 { file_mode = 1 }
FNR==1 {
  if (ARGIND==1) file_mode=1; else file_mode=2
  if (has_header==1) {
    if (file_mode==1) {
      nsrc_cols = NF
      for (i=1;i<=NF;i++){ shdr[i]=trim($i) }
      build_header_index(shdr, NF, shmap)
    } else {
      ntgt_cols = NF
      for (i=1;i<=NF;i++){ thdr[i]=trim($i) }
      build_header_index(thdr, NF, thmap)
    }
    next
  }
}

{
  if (has_header==0) {
    if (ARGIND==1) { if (NF>nsrc_cols) nsrc_cols=NF }
    else           { if (NF>ntgt_cols) ntgt_cols=NF }
  }
  if (!keys_resolved && ARGIND==1) {
    if (has_header==1) nk = parse_key_indexes(key_spec, 1, shmap, kidx)
    else               nk = parse_key_indexes(key_spec, 0, shmap, kidx)
    keys_resolved=1
  }
  key = make_key(kidx, nk)
  if (ARGIND==1) { if (++src_dupcount[key] > 1) { } src_row[key] = $0 }
  else           { if (++tgt_dupcount[key] > 1) { } tgt_row[key] = $0 }
}

END{
  schema_warns = 0
  print "SCHEMA CHECK" > out_schema
  if (has_header==1) {
    if (nsrc_cols != ntgt_cols) {
      printf("Different column counts (source=%d, target=%d)\n", nsrc_cols, ntgt_cols) >> out_schema; schema_warns++
    }
    maxc = (nsrc_cols>ntgt_cols?nsrc_cols:ntgt_cols)
    for (i=1;i<=maxc;i++) {
      sname = (i in shdr?shdr[i]:"<missing>")
      tname = (i in thdr?thdr[i]:"<missing>")
      if (sname != tname) {
        printf("Col %d differs: source=\"%s\" vs target=\"%s\"\n", i, sname, tname) >> out_schema; schema_warns++
      }
    }
    if (schema_warns==0) print "Headers match." >> out_schema
  } else {
    if (nsrc_cols != ntgt_cols) { printf("Different column counts (source=%d, target=%d)\n", nsrc_cols, ntgt_cols) >> out_schema; schema_warns++ }
    else                        { printf("No header; both have %d columns.\n", nsrc_cols) >> out_schema }
  }

  print "key" > out_missing
  print "key" > out_extra
  print "key,count" > out_dups_src
  print "key,count" > out_dups_tgt
  if (has_header==1) print "key,column_index,column_name,source_value,target_value,is_numeric,diff" > out_mismatch
  else               print "key,column_index,source_value,target_value,is_numeric,diff" > out_mismatch

  missing_cnt=0; extra_cnt=0; mismatch_cnt=0; dup_s_cnt=0; dup_t_cnt=0; common_cnt=0;

  for (k in src_row) if (!(k in tgt_row)) { print csv_safe(k) >> out_missing; missing_cnt++ }
  for (k in tgt_row) if (!(k in src_row)) { print csv_safe(k) >> out_extra;  extra_cnt++   }

  for (k in src_dupcount) if (src_dupcount[k] > 1) { printf("%s,%d\n", csv_safe(k), src_dupcount[k]) >> out_dups_src; dup_s_cnt++ }
  for (k in tgt_dupcount) if (tgt_dupcount[k] > 1) { printf("%s,%d\n", csv_safe(k), tgt_dupcount[k]) >> out_dups_tgt; dup_t_cnt++ }

  ncols = (has_header==1 ? nsrc_cols : (nsrc_cols>ntgt_cols?nsrc_cols:ntgt_cols))
  for (k in src_row) if (k in tgt_row) {
    common_cnt++
    n1 = split(src_row[k], S, FS)
    n2 = split(tgt_row[k], T, FS)
    maxc = (n1>n2?n1:n2)
    for (i=1;i<=maxc;i++) {
      s = (i<=n1 ? trim(S[i]) : ""); t = (i<=n2 ? trim(T[i]) : "")
      skip=0; for (j=1;j<=nk;j++) if (i==kidx[j]) { skip=1; break }
      if (skip) continue
      if (!equal_with_tol(s, t)) {
        isn = (isnum(s) && isnum(t)) ? "1" : "0"
        d = (isn=="1" ? (s==""||t==""? "": (s - t)) : "")
        if (has_header==1) { cname = (i in shdr ? shdr[i] : "")
          printf("%s,%d,%s,%s,%s,%s,%s\n", csv_safe(k), i, csv_safe(cname), csv_safe(s), csv_safe(t), isn, d) >> out_mismatch
        } else {
          printf("%s,%d,%s,%s,%s,%s\n", csv_safe(k), i, csv_safe(s), csv_safe(t), isn, d) >> out_mismatch
        }
        mismatch_cnt++
      }
    }
  }

  print "RECONCILIATION SUMMARY" > out_summary
  printf("Source file:%s\n", src_file) >> out_summary
  printf("Target file:%s\n", tgt_file) >> out_summary
  printf("Delimiter:%s\n", (FS=="\t"?"TAB":FS)) >> out_summary
  printf("Header:%s\n", (has_header==1?"yes":"no")) >> out_summary
  printf("Key spec:%s\n", key_spec) >> out_summary
  printf("Numeric tolerance:%s\n", tol) >> out_summary
  printf("----\n") >> out_summary
  printf("Keys only in source (missing in target):%d\n", missing_cnt) >> out_summary
  printf("Keys only in target (extra in target):%d\n", extra_cnt) >> out_summary
  printf("Duplicate keys in source:%d\n", dup_s_cnt) >> out_summary
  printf("Duplicate keys in target:%d\n", dup_t_cnt) >> out_summary
  printf("Common keys:%d\n", common_cnt) >> out_summary
  printf("Mismatched values (non-key columns):%d\n", mismatch_cnt) >> out_summary
  printf("Schema issues noted:%s\n", (schema_warns>0?"yes":"no")) >> out_summary
}
' "$SRC" "$TGT"

# --- Build a single Excel-friendly file with two worksheets (Schema_Diff & Summary) ---
# We emit SpreadsheetML 2003 XML so Excel opens it directly.
OVXML="${PREFIX}_overview.xml"

{
  cat <<'XMLHEAD'
<?xml version="1.0"?>
<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet"
          xmlns:o="urn:schemas-microsoft-com:office:office"
          xmlns:x="urn:schemas-microsoft-com:office:excel"
          xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">
XMLHEAD

  # Worksheet 1: Schema_Diff (each line as one cell in a row)
  echo '<Worksheet ss:Name="Schema_Diff"><Table>'
  awk '
    function xml_escape(s){ gsub(/&/,"&amp;",s); gsub(/</,"&lt;",s); gsub(/>/,"&gt;",s); gsub(/"/,"&quot;",s); return s }
    { s=$0; print "  <Row><Cell><Data ss:Type=\"String\">" xml_escape(s) "</Data></Cell></Row>" }
  ' "${PREFIX}_schema_diff.txt"
  echo '</Table></Worksheet>'

  # Worksheet 2: Summary (split "label:value" into two cells when possible)
  echo '<Worksheet ss:Name="Summary"><Table>'
  awk -F':' '
    function xml_escape(s){ gsub(/&/,"&amp;",s); gsub(/</,"&lt;",s); gsub(/>/,"&gt;",s); gsub(/"/,"&quot;",s); return s }
    {
      if ($0 ~ /^-+$/ || $0 ~ /^RECONCILIATION SUMMARY$/) {
        # keep section headings / dividers as one-cell rows
        s=$0
        print "  <Row><Cell><Data ss:Type=\"String\">" xml_escape(s) "</Data></Cell></Row>"
      } else if (NF>=2) {
        left=$1; sub(/^[ \t]+|[ \t]+$/,"",left)
        right=$0; sub(/^[^:]*:/,"",right); sub(/^[ \t]+/,"",right)
        print "  <Row>" \
              "<Cell><Data ss:Type=\"String\">" xml_escape(left) "</Data></Cell>" \
              "<Cell><Data ss:Type=\"String\">" xml_escape(right) "</Data></Cell>" \
              "</Row>"
      } else {
        s=$0
        print "  <Row><Cell><Data ss:Type=\"String\">" xml_escape(s) "</Data></Cell></Row>"
      }
    }
  ' "${PREFIX}_summary.txt"
  echo '</Table></Worksheet>'

  echo '</Workbook>'
} > "$OVXML"

echo "Done."
echo "Reports:"
echo "  ${PREFIX}_summary.txt"
echo "  ${PREFIX}_schema_diff.txt"
echo "  ${PREFIX}_overview.xml   (Open in Excel; contains both sheets)"
echo "  ${PREFIX}_missing_in_target.csv"
echo "  ${PREFIX}_extra_in_target.csv"
echo "  ${PREFIX}_mismatched_values.csv"
echo "  ${PREFIX}_duplicates_source.csv"
echo "  ${PREFIX}_duplicates_target.csv"
