// SPDX-FileCopyrightText: 2026 Alessandro Gregucci
// SPDX-License-Identifier: GPL-3.0-or-later
// Distribution wrapper only; scientific processing remains in the Python app.
// Build with tools/build_portable.py. Paint feedback before extracting the
// reviewed ZIP in a background task; retain its libraries until desktop exit.

using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;

[assembly: AssemblyTitle("battread")]
[assembly: AssemblyCompany("Alessandro Gregucci")]
[assembly: AssemblyCopyright("Copyright 2026 Alessandro Gregucci")]
[assembly: AssemblyVersion("0.1.0.0")]
[assembly: AssemblyFileVersion("0.1.0.0")]

/// <summary>Own the startup notice and one temporary app instance.</summary>
internal static class PortableLauncher
{
    /// <summary>Paint feedback first, then retain the launcher while the desktop runs.</summary>
    [STAThread]
    private static int Main()
    {
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        using (Form notice = CreateNotice())
        {
            Task<int> lifetime = null;
            bool handedOff = false;
            // No close button: prevent Alt-F4 from orphaning extraction. Normal
            // desktop closure remains available once startup has completed.
            notice.FormClosing += delegate(object sender, FormClosingEventArgs args)
            {
                if (!handedOff) args.Cancel = true;
            };
            notice.Shown += delegate
            {
                notice.Update();
                lifetime = Task.Run(() => RunDesktop(notice, () =>
                {
                    handedOff = true;
                    notice.Close();
                }));
            };
            Application.Run(notice);
            return lifetime == null ? 1 : lifetime.GetAwaiter().GetResult();
        }
    }

    /// <summary>Create monochrome feedback without a console or installer interface.</summary>
    private static Form CreateNotice()
    {
        Form form = new Form();
        form.Text = "battread startup";
        form.StartPosition = FormStartPosition.CenterScreen;
        form.FormBorderStyle = FormBorderStyle.FixedSingle;
        form.ControlBox = false;
        form.ShowInTaskbar = false;
        form.ClientSize = new Size(400, 90);
        form.BackColor = Color.FromArgb(245, 245, 245);
        form.Font = new Font("Segoe UI", 12);
        Label label = new Label();
        label.Dock = DockStyle.Fill;
        label.Text = "Starting battread...";
        label.TextAlign = ContentAlignment.MiddleCenter;
        label.ForeColor = Color.FromArgb(70, 70, 70);
        form.Controls.Add(label);
        return form;
    }

    /// <summary>Extract sequentially, hand off feedback, and clean after desktop exit.</summary>
    private static int RunDesktop(Form notice, Action closeNotice)
    {
        string temporaryBase = Path.GetFullPath(Path.GetTempPath());
        string root = Path.GetFullPath(Path.Combine(
            temporaryBase, "battread-app-" + Guid.NewGuid()));
        string temporaryPrefix = temporaryBase.TrimEnd(Path.DirectorySeparatorChar)
            + Path.DirectorySeparatorChar;
        bool rootIsValid = root.StartsWith(temporaryPrefix,
            StringComparison.OrdinalIgnoreCase);
        try
        {
            if (!rootIsValid) throw new IOException("Invalid temporary application path.");
            Directory.CreateDirectory(root);
            ExtractPayload(root);
            string ready = Path.Combine(root, "desktop-ready");
            ProcessStartInfo command = new ProcessStartInfo(
                Path.Combine(root, "battread", "battread.exe"));
            command.UseShellExecute = false;
            command.CreateNoWindow = true;
            command.EnvironmentVariables["BATTREAD_STARTUP_READY"] = ready;
            command.EnvironmentVariables["PYINSTALLER_RESET_ENVIRONMENT"] = "1";
            using (Process desktop = Process.Start(command))
            {
                if (desktop == null) throw new IOException("Could not launch the desktop app.");
                while (!File.Exists(ready) && !desktop.WaitForExit(50)) { }
                notice.BeginInvoke(closeNotice);
                desktop.WaitForExit();
                return desktop.ExitCode;
            }
        }
        catch (Exception error)
        {
            notice.Invoke(new Action(() =>
            {
                MessageBox.Show(notice, "battread could not start.\n\n" + error.Message,
                    "battread", MessageBoxButtons.OK, MessageBoxIcon.Error);
                closeNotice();
            }));
            return 1;
        }
        finally
        {
            // Antivirus can briefly hold closed executables; retry deletion only
            // within this randomly named root, never another application's files.
            for (int attempt = 0; rootIsValid && attempt < 5; attempt++)
            {
                try { if (Directory.Exists(root)) Directory.Delete(root, true); break; }
                catch (IOException) { Thread.Sleep(200); }
                catch (UnauthorizedAccessException) { Thread.Sleep(200); }
            }
        }
    }

    /// <summary>Stream the embedded ZIP to checked paths under this instance's root.</summary>
    private static void ExtractPayload(string root)
    {
        string prefix = Path.GetFullPath(root) + Path.DirectorySeparatorChar;
        using (Stream payload = Assembly.GetExecutingAssembly().GetManifestResourceStream(
            "battread_payload"))
        {
            if (payload == null) throw new IOException("The application payload is missing.");
            using (ZipArchive archive = new ZipArchive(payload, ZipArchiveMode.Read))
            {
                foreach (ZipArchiveEntry entry in archive.Entries)
                {
                    string target = Path.GetFullPath(Path.Combine(root, entry.FullName));
                    if (!target.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
                        throw new IOException("An application archive path is invalid.");
                    if (String.IsNullOrEmpty(entry.Name))
                    {
                        Directory.CreateDirectory(target);
                        continue;
                    }
                    Directory.CreateDirectory(Path.GetDirectoryName(target));
                    using (Stream input = entry.Open())
                    using (FileStream output = new FileStream(target, FileMode.CreateNew))
                        input.CopyTo(output, 81920);
                }
            }
        }
    }
}
