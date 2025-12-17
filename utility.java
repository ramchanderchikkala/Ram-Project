import java.io.*;
import java.nio.file.*;
import java.util.*;
import java.util.regex.*;
import java.time.*;

public class utility {

    // Declaring the required lists
    static List<String> source_file_list = new ArrayList<>();
    static List<String> destination_file_list = new ArrayList<>();
    static List<Map<String, List<String>>> primary_key_list = new ArrayList<>();
    static List<String> table_list = new ArrayList<>();

    // CONFIGURATION SECTION
    static String GIT_BASH_PATH = "C:\\Program Files\\Git\\bin\\bash.exe";
    static String RECON_SCRIPT = "./reconcillation.sh";

    // --------------------------------------------------------
    //  source_file
    // --------------------------------------------------------
    public static List<String> source_file(String source_path) {
        System.out.println("Inside the Source Path");
        File folder = new File(source_path);
        for (String file_name : Objects.requireNonNull(folder.list())) {
            source_file_list.add(file_name);
            table_list.add(file_name.split("\\.")[0]);
        }
        return source_file_list;
    }

    // --------------------------------------------------------
    //  destination_file
    // --------------------------------------------------------
    public static List<String> destination_file(String destination_path) {
        System.out.println("Inside the Destination Path");
        File folder = new File(destination_path);
        for (String file_name : Objects.requireNonNull(folder.list())) {
            destination_file_list.add(file_name);
        }
        return destination_file_list;
    }

    // --------------------------------------------------------
    //  Primary_file
    // --------------------------------------------------------
    public static List<Map<String, List<String>>> Primary_file(String primary_key_path) {

        System.out.println("Inside the Primary Key Path");

        try (BufferedReader br = new BufferedReader(new FileReader(primary_key_path))) {
            String line;

            while ((line = br.readLine()) != null) {
                line = line.strip();
                if (line.isEmpty()) continue;

                Map<String, List<String>> result = string_to_dict(line);
                primary_key_list.add(result);
            }
        } catch (Exception e) {
            e.printStackTrace();
        }

        return primary_key_list;
    }

    // --------------------------------------------------------
    //  string_to_dict
    // --------------------------------------------------------
    public static Map<String, List<String>> string_to_dict(String s) {

        if (!s.contains("=")) {
            throw new RuntimeException("Invalid primary key format. Expected 'table = key1,key2'");
        }

        String[] parts = s.split("=", 2);
        String key = parts[0].trim();
        String[] valuesRaw = parts[1].split(",");

        List<String> values = new ArrayList<>();
        for (String v : valuesRaw) values.add(v.trim());

        Map<String, List<String>> map = new HashMap<>();
        map.put(key, values);
        return map;
    }

    // --------------------------------------------------------
    //  find_exact_match
    // --------------------------------------------------------
    public static String find_exact_match(String input_str, List<String> patterns) {

        for (String pattern : patterns) {
            if (Pattern.compile(pattern, Pattern.CASE_INSENSITIVE).matcher(input_str).matches()) {
                return pattern;
            }
        }
        return null;
    }

    // --------------------------------------------------------
    //  create_folder
    // --------------------------------------------------------
    public static void create_folder(String folder_path) {
        try {
            Files.createDirectories(Paths.get(folder_path));
            System.out.println("Folder created: " + folder_path);
        } catch (Exception e) {
            e.printStackTrace();
        }
    }

    // --------------------------------------------------------
    //  command_execution
    // --------------------------------------------------------
    public static String command_execution(String source_file,
                                           String destination_file,
                                           String primary_key,
                                           String table_name) {

        System.out.println("Primary Key's    ::: " + primary_key);

        String cmd_str =
                RECON_SCRIPT + " " +
                "-s source/" + source_file + " " +
                "-t destination/" + destination_file + " " +
                "-k " + primary_key + " \",\" " +
                "-H 1";

        System.out.println(cmd_str);

        try {
            ProcessBuilder pb = new ProcessBuilder(GIT_BASH_PATH, "-c", cmd_str);
            pb.redirectErrorStream(true);

            Process process = pb.start();
            BufferedReader r = new BufferedReader(new InputStreamReader(process.getInputStream()));

            String line;
            while ((line = r.readLine()) != null) {
                System.out.println(line);
            }

            process.waitFor();
        } catch (Exception e) {
            e.printStackTrace();
        }

        // Create folder for results
        String table_folder = "results/" + table_name;
        create_folder(table_folder);

        // ---------------------------------------------------------
        // NEW: Move reconciliation output files into the table folder
        // ---------------------------------------------------------
        List<String> generated_files = Arrays.asList(
                "reconcile_summary.txt",
                "reconcile_schema_diff.txt",
                "reconcile_overview.xml",
                "reconcile_missing_in_target.csv",
                "reconcile_extra_in_target.csv",
                "reconcile_mismatched_values.csv",
                "reconcile_duplicates_source.csv",
                "reconcile_duplicates_target.csv"
        );

        for (String fname : generated_files) {
            File f = new File(fname);

            if (f.exists()) {
                File dest = new File(table_folder + "/" + fname);
                try {
                    Files.move(f.toPath(), dest.toPath(), StandardCopyOption.REPLACE_EXISTING);
                    System.out.println("Moved: " + fname + " -> " + table_folder);
                } catch (IOException e) {
                    System.out.println("Failed to move: " + fname);
                    e.printStackTrace();
                }
            } else {
                System.out.println("Missing file (skipped): " + fname);
            }
        }

        return "\n" + cmd_str;
    }

    // --------------------------------------------------------
    //  command_concat
    // --------------------------------------------------------
    public static String command_concat(List<String> source_file_list,
                                        List<String> destination_file_list,
                                        List<Map<String, List<String>>> primary_key_list) {

        System.out.println("Inside the command string building");

        String recon_cmd_str = "";

        for (String source : source_file_list) {

            System.out.println("Source File      ::: " + source);

            String table_name = source.split("\\.")[0];
            System.out.println("Table Name       ::: " + table_name);

            String match = find_exact_match(source, destination_file_list);
            if (match == null) {
                System.out.println("No Destination file for " + source + ". Skipping.");
                continue;
            }

            System.out.println("Destination File ::: " + match);

            List<String> primary_key_values = null;

            for (Map<String, List<String>> entry : primary_key_list) {
                if (entry.containsKey(table_name)) {
                    primary_key_values = entry.get(table_name);
                } else {
                    System.out.println("No primary key entry for table " + table_name + " in this entry.");
                }
            }

            if (primary_key_values == null) {
                System.out.println("No primary key found for table " + table_name + ", skipping.");
                continue;
            }

            String primary_key = String.join(",", primary_key_values);

            recon_cmd_str += command_execution(source, match, primary_key, table_name);
        }

        return recon_cmd_str;
    }

    // --------------------------------------------------------
    //  main_program
    // --------------------------------------------------------
    public static void main_program() {

        System.out.println("Inside Main Function");

        String source_path = "source/";
        String destination_path = "destination/";
        String primary_key_path = "primary_key/primarykey.csv";

        List<String> src_list = source_file(source_path);
        List<String> dst_list = destination_file(destination_path);
        List<Map<String, List<String>>> pk_list = Primary_file(primary_key_path);

        String recon_command = command_concat(src_list, dst_list, pk_list);

        create_folder("recon_command");

        try (FileWriter fw = new FileWriter("recon_command/Recon_commands.txt")) {
            fw.write(recon_command);
        } catch (Exception e) {
            e.printStackTrace();
        }

        System.out.println("File created and content written successfully!");
    }

    // --------------------------------------------------------
    //  clean folders
    // --------------------------------------------------------
    public static void cleanFolder(String path) {
        try {
            File folder = new File(path);
            if (!folder.exists()) return;

            for (File f : Objects.requireNonNull(folder.listFiles())) {
                if (f.isDirectory()) deleteDirectory(f.toPath());
                else f.delete();
            }
        } catch (Exception e) {}
    }

    public static void deleteDirectory(Path dir) throws IOException {
        Files.walk(dir)
                .sorted(Comparator.reverseOrder())
                .map(Path::toFile)
                .forEach(File::delete);
    }

    // --------------------------------------------------------
    //  main
    // --------------------------------------------------------
    public static void main(String[] args) {

        System.out.println("--------------------------------------------- STARTS HERE ---------------------------------------------");

        LocalDateTime start_time = LocalDateTime.now();

        cleanFolder("./results");
        cleanFolder("./recon_command");

        main_program();

        LocalDateTime end_time = LocalDateTime.now();
        System.out.println("Total Time taken for execution ::: " +
                java.time.Duration.between(start_time, end_time));

        System.out.println("--------------------------------------------- END'S HERE ---------------------------------------------");
    }
}
