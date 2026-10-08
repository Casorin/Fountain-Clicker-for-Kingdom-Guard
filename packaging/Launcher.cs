using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

internal static class Launcher
{
    [STAThread]
    private static int Main(string[] args)
    {
        string root = AppDomain.CurrentDomain.BaseDirectory;
        string python = Path.Combine(root, ".python", "pythonw.exe");
        string script = Path.Combine(root, "scripts", "launch_portable.py");
        if (!File.Exists(python) || !File.Exists(script))
        {
            MessageBox.Show("Распакуйте весь архив и запускайте программу из полученной папки.",
                            "Фонтан", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return 1;
        }
        if (args.Length == 1 && args[0] == "--launcher-check") return 0;
        try
        {
            ProcessStartInfo info = new ProcessStartInfo(python, "-I \"" + script + "\"");
            info.WorkingDirectory = root;
            info.UseShellExecute = false;
            info.CreateNoWindow = true;
            info.EnvironmentVariables.Remove("PYTHONHOME");
            info.EnvironmentVariables.Remove("PYTHONPATH");
            info.EnvironmentVariables["PYTHONNOUSERSITE"] = "1";
            Process.Start(info);
            return 0;
        }
        catch (Exception)
        {
            MessageBox.Show("Не удалось открыть программу. Проверьте, что архив полностью распакован.",
                            "Фонтан", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }
}
