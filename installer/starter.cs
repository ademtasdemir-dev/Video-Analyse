// YVdctuAio.exe: startet das Programm ohne schwarzes Fenster.
// Liegt neben den Ordnern "python" (Python mit allen Paketen), "app" (das Programm) und "modelle".
// Liegt daneben die Datei "portabel.txt", bleiben alle Daten im Ordner "daten" neben der Exe (portable Version).
using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Windows.Forms;

[assembly: AssemblyTitle("YVdctuAio")]
[assembly: AssemblyDescription("YouTube, Video-Download, Cuts, Transkript, Upload - All in one")]
[assembly: AssemblyCompany("LAG|ZERØ")]
[assembly: AssemblyProduct("YVdctuAio")]
[assembly: AssemblyCopyright("LAG|ZERØ")]
[assembly: AssemblyVersion("1.1.0.0")]
[assembly: AssemblyFileVersion("1.1.0.0")]

static class Starter
{
    [STAThread]
    static int Main()
    {
        string basis = AppDomain.CurrentDomain.BaseDirectory;
        string python = Path.Combine(basis, "python", "python.exe");
        string app = Path.Combine(basis, "app");
        if (!File.Exists(python) || !Directory.Exists(app))
        {
            Melden("YVdctuAio ist unvollständig: Die Ordner \"python\" und \"app\" fehlen neben dieser Datei.\n\nBitte neu installieren.");
            return 2;
        }
        if (!File.Exists(Path.Combine(Environment.SystemDirectory, "msvcp140.dll")))
        {
            Melden("Auf diesem PC fehlt die Microsoft Visual C++ Laufzeit (kostenlos von Microsoft).\n\n"
                 + "Bitte von https://aka.ms/vs/17/release/vc_redist.x64.exe installieren und YVdctuAio danach noch einmal starten.");
            return 3;
        }
        var start = new ProcessStartInfo(python, "-m videoanalyse.programm");
        start.WorkingDirectory = app;
        start.UseShellExecute = false;
        start.CreateNoWindow = true;
        start.EnvironmentVariables["PYTHONUTF8"] = "1";
        string daten;
        if (File.Exists(Path.Combine(basis, "portabel.txt")))
        {
            daten = Path.GetFullPath(Path.Combine(basis, "..", "daten"));
            start.EnvironmentVariables["VA_DATEN"] = daten;
        }
        else
        {
            daten = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "YVdctuAio", "daten");
        }
        try
        {
            using (Process p = Process.Start(start))
            {
                p.WaitForExit();
                if (p.ExitCode != 0)
                {
                    Melden("YVdctuAio wurde unerwartet beendet (Fehler " + p.ExitCode + ").\n\nWas passiert ist, steht in:\n"
                         + Path.Combine(daten, "protokoll.log"));
                    return 1;
                }
            }
        }
        catch (Exception e)
        {
            Melden("YVdctuAio konnte nicht gestartet werden:\n" + e.Message);
            return 1;
        }
        return 0;
    }

    static void Melden(string text)
    {
        MessageBox.Show(text, "YVdctuAio", MessageBoxButtons.OK, MessageBoxIcon.Error);
    }
}
