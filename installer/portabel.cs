// YVdctuAio-Portable.exe: eine einzelne Datei ohne Installation.
// Beim ersten Start entpackt sie das Programm einmalig in den Ordner "YVdctuAio-Portable" neben sich und startet es.
// Danach startet sie sofort. Das Programm selbst hängt als ZIP am Ende dieser Datei, die letzten 8 Bytes sind seine Länge.
using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Threading;
using System.Windows.Forms;

[assembly: AssemblyTitle("YVdctuAio Portable")]
[assembly: AssemblyDescription("YouTube, Video-Download, Cuts, Transkript, Upload - All in one (ohne Installation)")]
[assembly: AssemblyCompany("LAG|ZERØ")]
[assembly: AssemblyProduct("YVdctuAio")]
[assembly: AssemblyCopyright("LAG|ZERØ")]
[assembly: AssemblyVersion("1.1.0.0")]
[assembly: AssemblyFileVersion("1.1.0.0")]

// Liest nur den ZIP-Teil am Ende der Exe, als wäre er eine eigene Datei.
class Ausschnitt : Stream
{
    readonly Stream quelle; readonly long anfang, laenge; long stelle;
    public Ausschnitt(Stream quelle, long anfang, long laenge) { this.quelle = quelle; this.anfang = anfang; this.laenge = laenge; }
    public override bool CanRead { get { return true; } }
    public override bool CanSeek { get { return true; } }
    public override bool CanWrite { get { return false; } }
    public override long Length { get { return laenge; } }
    public override long Position { get { return stelle; } set { stelle = value; } }
    public override void Flush() { }
    public override int Read(byte[] puffer, int ab, int anzahl)
    {
        long rest = laenge - stelle;
        if (rest <= 0) return 0;
        if (anzahl > rest) anzahl = (int)rest;
        quelle.Position = anfang + stelle;
        int gelesen = quelle.Read(puffer, ab, anzahl);
        stelle += gelesen;
        return gelesen;
    }
    public override long Seek(long versatz, SeekOrigin von)
    {
        stelle = von == SeekOrigin.Begin ? versatz : von == SeekOrigin.Current ? stelle + versatz : laenge + versatz;
        return stelle;
    }
    public override void SetLength(long wert) { throw new NotSupportedException(); }
    public override void Write(byte[] puffer, int ab, int anzahl) { throw new NotSupportedException(); }
}

static class Portabel
{
    const string VERSION = "1.1.0";
    static string fehler;

    [STAThread]
    static int Main()
    {
        string exe = Assembly.GetExecutingAssembly().Location;
        string ziel = Path.Combine(Path.GetDirectoryName(exe), "YVdctuAio-Portable");
        string programm = Path.Combine(ziel, "programm");
        string marke = Path.Combine(programm, "version.txt");
        try
        {
            if (!File.Exists(marke) || File.ReadAllText(marke).Trim() != VERSION)
            {
                if (!Entpacken(exe, programm)) return 1;
                File.WriteAllText(marke, VERSION);
            }
            var start = new ProcessStartInfo(Path.Combine(programm, "YVdctuAio.exe"));
            start.WorkingDirectory = programm;
            start.UseShellExecute = false;
            Process.Start(start);
            return 0;
        }
        catch (Exception e)
        {
            MessageBox.Show("YVdctuAio konnte nicht gestartet werden:\n" + e.Message
                + "\n\nDie portable Datei braucht einen Ordner, in den sie schreiben darf (zum Beispiel den Desktop oder einen USB-Stick).",
                "YVdctuAio Portable", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }

    static bool Entpacken(string exe, string programm)
    {
        Application.EnableVisualStyles();
        var fenster = new Form();
        fenster.Text = "YVdctuAio Portable";
        fenster.ClientSize = new Size(460, 120);
        fenster.FormBorderStyle = FormBorderStyle.FixedDialog;
        fenster.MaximizeBox = false; fenster.MinimizeBox = false; fenster.ControlBox = false;
        fenster.StartPosition = FormStartPosition.CenterScreen;
        fenster.Icon = Icon.ExtractAssociatedIcon(exe);
        var text = new Label();
        text.Text = "YVdctuAio wird einmalig entpackt (etwa 1,6 GB). Das dauert ein bis zwei Minuten …";
        text.SetBounds(18, 16, 424, 40);
        var balken = new ProgressBar();
        balken.SetBounds(18, 66, 424, 24); balken.Maximum = 1000;
        fenster.Controls.Add(text); fenster.Controls.Add(balken);
        var arbeit = new Thread(delegate ()
        {
            try
            {
                if (Directory.Exists(programm)) Directory.Delete(programm, true);  // alte Version ersetzen; "daten" daneben bleibt
                Directory.CreateDirectory(programm);
                using (var datei = new FileStream(exe, FileMode.Open, FileAccess.Read, FileShare.Read))
                {
                    var ende = new byte[8];
                    datei.Position = datei.Length - 8;
                    datei.Read(ende, 0, 8);
                    long laenge = BitConverter.ToInt64(ende, 0);
                    if (laenge <= 0 || laenge > datei.Length - 8) throw new InvalidDataException("Die Datei ist unvollständig. Bitte noch einmal herunterladen.");
                    using (var zip = new ZipArchive(new Ausschnitt(datei, datei.Length - 8 - laenge, laenge), ZipArchiveMode.Read))
                    {
                        int gesamt = zip.Entries.Count, nr = 0;
                        string wurzel = Path.GetFullPath(programm) + Path.DirectorySeparatorChar;
                        foreach (ZipArchiveEntry eintrag in zip.Entries)
                        {
                            string pfad = Path.GetFullPath(Path.Combine(programm, eintrag.FullName));
                            if (!pfad.StartsWith(wurzel, StringComparison.OrdinalIgnoreCase)) throw new InvalidDataException("Ungültiger Eintrag im Paket.");
                            if (eintrag.FullName.EndsWith("/")) { Directory.CreateDirectory(pfad); }
                            else
                            {
                                Directory.CreateDirectory(Path.GetDirectoryName(pfad));
                                eintrag.ExtractToFile(pfad, true);
                            }
                            nr++;
                            if (nr % 50 == 0 || nr == gesamt)
                            {
                                int wert = (int)(1000L * nr / gesamt);
                                fenster.BeginInvoke((MethodInvoker)delegate { balken.Value = wert; });
                            }
                        }
                    }
                }
            }
            catch (Exception e) { fehler = e.Message; }
            fenster.BeginInvoke((MethodInvoker)delegate { fenster.Close(); });
        });
        fenster.Shown += delegate { arbeit.Start(); };
        Application.Run(fenster);
        if (fehler != null)
        {
            MessageBox.Show("Das Entpacken hat nicht geklappt:\n" + fehler, "YVdctuAio Portable", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return false;
        }
        return true;
    }
}
