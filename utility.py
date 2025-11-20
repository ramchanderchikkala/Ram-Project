import pandas as pd
import numpy as np
from datetime import datetime
import os

source_file_list = []
destination_file_list = []

def source_file(source_path):

    print("Inside the Source Path ")

    for file_name in os.listdir(source_path):
        source_file_list.append(file_name)

    return source_file_list


def destination_file(destination_path):

    print("Inside the Destination Path ")

    for file_name in os.listdir(destination_path):
        destination_file_list.append(file_name)

    return destination_file_list

def Primary_file(primary_key_path):

    print("Inside the Primary Key Path ")

    #df_pk = pd.read_csv(primary_key_path)

def command_concat(source_file,destination_file, primary_key):

    print("Inside the command string building")

    cmd_str = "./reconcillation.sh -s " + source_file + " -t " + destination_file + " -k " + primary_key + " ',' " + " -H 1"

    print(cmd_str)

def main():

    print("Inside Main Function")

    source_path = "source/"
    destination_path = "destination/"
    primary_key_path = "primary_key/primarykey.csv"

    source_file(source_path)

    destination_file(destination_path)

    Primary_file(primary_key_path)

    command_concat("apple_products.csv","apple_products1.csv", "Product_Name")

if __name__ == "__main__":

    start_time = datetime.now()

    main()

    end_time = datetime.now()

    print(end_time - start_time)
