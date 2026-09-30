using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Management;
using System.Windows.Forms;

internal static class SigilMCPExternal
{
    private static string Quote(string value)
    {
        return "\"" + value.Replace("\"", "\\\"") + "\"";
    }

    private static string ParentDirectory()
    {
        try {
            int id = Process.GetCurrentProcess().Id;
            using (ManagementObjectSearcher query = new ManagementObjectSearcher(
                "SELECT ParentProcessId FROM Win32_Process WHERE ProcessId=" + id)) {
                foreach (ManagementObject row in query.Get()) {
                    using (Process parent = Process.GetProcessById(Convert.ToInt32(row["ParentProcessId"])))
                        return Path.GetDirectoryName(parent.MainModule.FileName);
                }
            }
        } catch { }
        return null;
    }

    private static string FindOnPath(string name)
    {
        if (String.IsNullOrWhiteSpace(name)) return null;
        if (File.Exists(name)) return Path.GetFullPath(name);
        foreach (string directory in (Environment.GetEnvironmentVariable("PATH") ?? "").Split(Path.PathSeparator)) {
            try {
                string candidate = Path.Combine(directory.Trim('"'), name);
                if (File.Exists(candidate)) return candidate;
            } catch { }
        }
        return null;
    }

    private static string FindPython()
    {
        string configured = Environment.GetEnvironmentVariable("SIGIL_PYTHON");
        string parent = ParentDirectory();
        List<string> candidates = new List<string> {
            configured,
            parent == null ? null : Path.Combine(parent, "python3.exe"),
            Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "python3.exe"),
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), "Sigil", "python3.exe"),
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs", "Sigil", "python3.exe"),
            FindOnPath("python3.exe"), FindOnPath("python.exe")
        };
        foreach (string candidate in candidates)
            if (!String.IsNullOrWhiteSpace(candidate) && File.Exists(candidate)) return candidate;
        return null;
    }

    [STAThread]
    private static int Main(string[] args)
    {
        if (args.Length == 0) return 2;
        string directory = AppDomain.CurrentDomain.BaseDirectory;
        string python = FindPython();
        if (python == null) {
            MessageBox.Show("Python 3 não foi encontrado. Defina SIGIL_PYTHON com o caminho do python3.exe do Sigil.",
                            "Sigil MCP Bridge", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 3;
        }
        string script = Path.Combine(directory, "external_bridge.py");
        string arguments = Quote(script);
        foreach (string arg in args) arguments += " " + Quote(arg);
        ProcessStartInfo start = new ProcessStartInfo(python, arguments) {
            UseShellExecute = false,
            CreateNoWindow = true,
            WorkingDirectory = directory,
            RedirectStandardError = true
        };
        using (Process process = Process.Start(start)) {
            string error = process.StandardError.ReadToEnd();
            process.WaitForExit();
            if (process.ExitCode != 0)
                MessageBox.Show(String.IsNullOrWhiteSpace(error) ? "O bridge encerrou com erro." : error,
                                "Sigil MCP Bridge", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return process.ExitCode;
        }
    }
}
