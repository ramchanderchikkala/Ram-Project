import os
import glob
import re
import subprocess
from datetime import datetime
import shutil

# Declaring the required lists
source_file_list = []
destination_file_list = []
primary_key_list = []
table_list = []

# >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
#  CONFIGURATION SECTION (EDIT IF NEEDED)
# >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>

# Full Windows path to Git Bash
GIT_BASH_PATH = r"C:\Program Files\Git\usr\bin\bash.exe"

# Full Git-Bash style path to your reconcillation.sh
#RECON_SCRIPT = "/c/Users/ramch/My_Computer/Drive_D/CodeBase/Ram-Project/reconcillation.sh"
RECON_SCRIPT = "./reconcillation.sh"


def source_file(source_path: str):
    print("Inside the Source Path")
    for file_name in os.listdir(source_path):
        source_file_list.append(file_name)
        table_list.append(file_name.split(".")[0])
    return source_file_list


def destination_file(destination_path: str):
    print("Inside the Destination Path")
    for file_name in os.listdir(destination_path):
        destination_file_list.append(file_name)
    return destination_file_list


def Primary_file(primary_key_path: str):
    print("Inside the Primary Key Path")

    with open(primary_key_path, "r") as file:
        for line in file:
            line = line.strip()
            if not line:
                continue
            result = string_to_dict(line)
            #print("primary_key", result)
            primary_key_list.append(result)

    #print("primary_key_list ::: ", primary_key_list)
    return primary_key_list


def string_to_dict(s: str):
    if "=" not in s:
        raise ValueError("Invalid primary key format. Expected 'table = key1,key2'")

    key_part, value_part = s.split("=", 1)
    key = key_part.strip()
    values = [v.strip() for v in value_part.split(",")]

    return {key: values}


def find_exact_match(input_str, patterns):
    for pattern in patterns:
        if isinstance(pattern, str) and re.fullmatch(pattern, input_str, re.IGNORECASE):
            return pattern
    return None


def create_folder(folder_path: str):
    os.makedirs(folder_path, exist_ok=True)
    print(f"Folder created: {folder_path}")


# >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
#  COMMAND EXECUTION SECTION
# >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>

def command_execution(source_file: str, destination_file: str, primary_key: str, table_name: str):
    print("Primary Key's    ::: ", primary_key)

    # FINAL FIXED COMMAND (no ",")
    cmd_str = (
        f"{RECON_SCRIPT} "
        f"-s source/{source_file} "
        f"-t destination/{destination_file} "
        f"-k {primary_key} \",\" "
        f"-H 1"
    )

    print(cmd_str)

    # Execute through Git Bash
    subprocess.run([r"C:/Program Files/Git/bin/bash.exe", "-c", cmd_str])

    # Create folder for results
    table_folder = os.path.join("results", table_name)
    create_folder(table_folder)

    # ---------------------------------------------------------
    # NEW: Move generated reconciliation files to table folder
    # ---------------------------------------------------------

    generated_files = [
        "reconcile_summary.txt",
        "reconcile_schema_diff.txt",
        "reconcile_overview.xml",
        "reconcile_missing_in_target.csv",
        "reconcile_extra_in_target.csv",
        "reconcile_mismatched_values.csv",
        "reconcile_duplicates_source.csv",
        "reconcile_duplicates_target.csv"
    ]

    for fname in generated_files:
        if os.path.exists(fname):
            shutil.move(fname, os.path.join(table_folder, fname))
            print(f"Moved: {fname} -> {table_folder}")
        else:
            print(f"Missing file (skipped): {fname}")

    return "\n" + cmd_str


def command_concat(source_file_list, destination_file_list, primary_key_list):
    print("Inside the command string building")

    recon_cmd_str = ""

    for source in source_file_list:
        print("Source File      ::: ", source)

        table_name = source.split(".")[0]
        print("Table Name       ::: ", table_name)

        # Check if matching destination exists
        match = find_exact_match(source, destination_file_list)
        if not match:
            print(f"No Destination file for {source}. Skipping.")
            continue

        destination_file_name = match
        print("Destination File ::: ", destination_file_name)

        # Find primary key for the table
        primary_key_values = ""
        for entry in primary_key_list:
            if table_name in entry:
                primary_key_values = entry[table_name]
            else:
                print(f"No primary key entry for table {table_name} in current entry.")

        if not primary_key_values:
            print(f"No primary key found for table {table_name}, skipping.")
            continue

        primary_key = ",".join(primary_key_values)

        # Execute one reconciliation command
        recon_cmd_str += command_execution(source, destination_file_name, primary_key, table_name)

    return recon_cmd_str


# >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>

def main():
    print("Inside Main Function")

    source_path = "source/"
    destination_path = "destination/"
    primary_key_path = "primary_key/primarykey.csv"

    src_list = source_file(source_path)
    dst_list = destination_file(destination_path)
    pk_list = Primary_file(primary_key_path)

    recon_command = command_concat(src_list, dst_list, pk_list)

    # Save commands
    os.makedirs("recon_command", exist_ok=True)
    with open("recon_command/Recon_commands.txt", "w") as file:
        file.write(recon_command)

    print("File created and content written successfully!")


# >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
#  SCRIPT ENTRY POINT
# >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>

if __name__ == "__main__":
    print("--------------------------------------------- STARTS HERE ---------------------------------------------")

    start_time = datetime.now()

    # Clean results folder
    for f in glob.glob("./results/*"):
        if os.path.isfile(f):
            os.remove(f)
        else:
            shutil.rmtree(f)

    # Clean recon_command folder
    for f in glob.glob("./recon_command/*"):
        if os.path.isfile(f):
            os.remove(f)
        else:
            shutil.rmtree(f)

    main()

    print("Total Time taken for execution ::: ", datetime.now() - start_time)
    print("--------------------------------------------- END'S HERE ---------------------------------------------")
