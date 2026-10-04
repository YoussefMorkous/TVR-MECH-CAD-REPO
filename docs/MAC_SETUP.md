# Mac setup: download projects and add STEP files

Use this guide on an Apple Silicon or Intel Mac. You do not need SOLIDWORKS or GitHub Desktop to download files or contribute STEP files.

The helper uploads your files for lead review. They become the approved team files after the lead merges your pull request. Adding a STEP file does not automatically update a SOLIDWORKS assembly.

## 1. Get your own GitHub account and repository access

1. Create an account at [github.com/signup](https://github.com/signup), if needed.
2. Send your GitHub username to Youssef and ask for repository **write access** if you will upload files.
3. Accept the repository invitation sent by GitHub before starting an upload.

Use your own account; do not share another member's sign-in.

## 2. Install Homebrew

Homebrew installs the tools the interface uses.

1. Press **Command + Space**, type **Terminal**, and press **Return**.
2. Open [brew.sh](https://brew.sh/).
3. Follow the installation instructions on that page. If you use its command, paste it into Terminal and press Return.
4. Complete the installer's **Next steps**, including the commands that add Homebrew to your PATH.
5. Open a new Terminal window and check:

```bash
brew --version
```

If this says `command not found`, complete Homebrew's Next steps before continuing. Check [Homebrew's supported macOS versions](https://docs.brew.sh/Installation) if your Mac is older.

## 3. Install Git, Git LFS, and GitHub CLI

Paste these commands into Terminal:

```bash
brew install git git-lfs gh
git lfs install
```

Check that all three tools are available:

```bash
git --version
git lfs version
gh --version
```

Each command should print a version. Git LFS is required to download actual CAD files rather than their small tracking records.

Official information: [Git LFS](https://git-lfs.com/) and [GitHub CLI for macOS](https://github.com/cli/cli/blob/trunk/docs/install_macos.md).

## 4. Install Python with the interface components

1. Open [Python's macOS downloads](https://www.python.org/downloads/macos/).
2. Choose a current stable Python 3 release, then its **macOS 64-bit universal2 installer**. This installer supports Intel and Apple Silicon.
3. Open the downloaded `.pkg` and complete the installation using the default options.

Use the Python.org installer for this guide: it includes Tk, the interface component. Apple's system Python or another Python installation may not include it. See [Python's Tk guidance](https://www.python.org/download/mac/tcltk/).

## 5. Sign in to GitHub

In Terminal, run:

```bash
gh auth login
```

Choose the following when asked:

- Account: **GitHub.com**.
- Git protocol: **HTTPS**.
- Authenticate Git using your GitHub credentials: **Yes**.
- Authentication method: **Login with a web browser**.

Follow the displayed browser instructions and sign in using your own account.

Then run:

```bash
gh auth setup-git
gh auth status
```

The status should show that you are signed in to GitHub.com.

## 6. Download the repository once

Run these commands one at a time:

```bash
cd ~
git clone https://github.com/YoussefMorkous/TVR-MECH-CAD-REPO.git
cd TVR-MECH-CAD-REPO
git lfs pull
```

Let the downloads finish. Do not use GitHub's green **Code > Download ZIP** button for CAD: that ZIP may contain LFS tracking records instead of real CAD files.

The repository is saved in your home folder:

```text
/Users/YOUR-MAC-USERNAME/TVR-MECH-CAD-REPO/
```

In Finder, choose **Go > Home**, then open **TVR-MECH-CAD-REPO**.

Keep this folder outside iCloud Drive, OneDrive, Dropbox, or other synchronized folders. The commands above save it directly in your home folder.

If the repository is already installed, use the update procedure near the end of this guide instead of cloning it over your existing files.

## 7. Set your name and email for uploads

While Terminal is inside the repository, run these commands with your own details:

```bash
git config user.name "Your Full Name"
git config user.email "your-github-email@example.com"
```

Replace the example name and email. Use an email associated with your GitHub account, or the private `noreply` address shown in [GitHub's email settings](https://github.com/settings/emails).

## 8. Open the interface and complete setup

Open Terminal and run these two commands:

```bash
cd ~/TVR-MECH-CAD-REPO
bash Start_CAD.command
```

1. The **TVR CAD Vault** interface should open.
2. Keep the Terminal window open while using the interface; it displays useful error details.
3. Click **One-time setup** and wait for the success message.
4. Click **Refresh projects**.
5. Choose the appropriate **Project** from the dropdown.

Use the same two commands each time you want to open the interface. Running the launcher with `bash` works without changing file permissions. The launcher checks for the required tools and finds the standard Python.org and Homebrew install locations.

The interface displays that project's folder next to **Assembly folder**. The existing rocket uses `cad/`; separate projects use `cad/projects/<project-id>/`. The file list shows the selected project's files.

## Download the latest approved project

1. Select the project.
2. Click **Download current / historic snapshot**.
3. Leave `origin/main` entered and confirm.
4. Choose a ZIP filename and destination, then wait for completion.
5. In Finder, double-click the ZIP to extract it.

This downloads the complete selected project, including its STEP and native CAD files. It does not reserve the project for editing and remains available while someone else is editing.

To download an older approved snapshot, enter its release tag or full commit ID instead of `origin/main`.

You still need suitable CAD software to view or edit the files. Downloading SOLIDWORKS files does not make desktop SOLIDWORKS run on macOS.

## Add STEP files to an existing project

1. Finish or cancel any earlier session. Click **Refresh projects**, then select the destination project.
2. Select an existing component in the file list as a reference for this contribution. **Start edit** currently requires at least one existing component to be selected; you do not have to modify it.
3. Click **Start edit**. Enter a clear reason, such as `Add Cage test bracket STEP model`.
4. Wait until the edit starts successfully. If someone is already editing this project, wait for them to finish.
5. Find the project folder shown under **Assembly folder** in Finder.
6. Copy your `.step` or `.stp` files into that folder. Use clear, unique names for new parts. Do not overwrite existing files unless that replacement is the intended change.
7. Return to the interface and click **Refresh file list**.
8. Select the new files and click **Add selected files to scope**. To select several separate files, hold **Command** while clicking.
9. Click **Submit for review**. Wait for the success message; the Terminal window displays the pull request link.
10. Keep the edit session until the lead reviews and merges the request. After merge, click **Finish after merge / closure**.

Git LFS stores STEP files automatically. You do not need to run `git add`, manually create a branch, or drag files into GitHub's website.

Existing parent assemblies are automatically allowed in scope, but unchanged assemblies are not uploaded as changes. A STEP-only contribution can be submitted without opening SOLIDWORKS. The lead still needs to check how the new geometry will be incorporated into the design.

The scope button authorizes changes to selected files; it does not copy or upload them. Copy files into the project folder first, then add them to scope and submit.

## Replace an existing STEP file

1. Refresh projects and choose the destination project before starting the edit.
2. Select the existing STEP file and click **Start edit**.
3. Replace that file in the displayed project folder, keeping its exact filename if it represents the same part.
4. Submit for review, then finish after merge.

Keep one current file for each part within a project. Git history preserves earlier revisions. Do not create `_Rev2`, `_final`, or another duplicate just to preserve an older revision of the same part.

For an independent part derived from another project, open the source in suitable CAD software, save a copy with a destination suffix such as `_CAGE`, and save it in the destination project. Make changes in the copy. Ask the lead to check references if you are copying native SOLIDWORKS files.

## Cancel an upload or recover work

If you decide not to submit, click **Cancel edit (keep backup)**. The helper preserves a project ZIP and recovery information in `exports/`, retains the edit branch, closes the session's open pull request, and releases locks after successful cleanup.

Closing the interface does not cancel the edit or release its locks. Reopen it to finish or cancel. If cleanup reports an error, preserve your files and retry or ask the lead; do not manually delete the session or remove other members' locks.

## Update an existing Mac installation

Do this after the lead merges a helper update. Finish or cancel your current edit, close the interface, and close any CAD application using this folder.

Then run:

```bash
cd ~/TVR-MECH-CAD-REPO
git switch main
git pull --ff-only origin main
git lfs pull
bash Start_CAD.command
```

If Git reports local changes, stop and preserve them. Do not use force, reset, or delete files to get past the error. Ask the lead to help reconcile the work.

## Common errors and questions

| Message or question | What to do |
| --- | --- |
| `brew: command not found` | Complete Homebrew's PATH instructions, then open a new Terminal window. |
| Python or Tk is missing | Install the Python.org macOS installer, then reopen `Start_CAD.command`. |
| Git, Git LFS, or GitHub CLI is missing | Repeat installation step 3, then reopen the launcher. |
| GitHub sign-in or permission error | Run `gh auth login`, then `gh auth setup-git`. Check that you accepted the repository invitation and have write access for uploads. |
| Git asks who you are | Complete the name and email commands in step 7. |
| `Select at least one component` | Select an existing component before Start edit. For a new file contribution, it is a reference only and can remain unchanged. |
| `Unexpected changes` | Refresh the file list and add your intended files to scope. Check that you have not changed files in another project. |
| The project is being edited | Wait for the other member to finish. Downloads are still available. |
| New project is missing | Finish or cancel your session, then click Refresh projects. A newly imported project appears after its pull request is merged. |
| Can I create a STEP-only project? | Not through the current Add project workflow. Initial project imports require a `.sldasm` assembly. Ask the lead to prepare the project first, then add STEP files to it. |
| Should I use Import returned ZIP for a few new files? | No. That import expects a complete selected-project package. For individual STEP additions, use the copy-and-scope procedure above. |
| Do I need SOLIDWORKS just to upload files? | No. The lead handles SOLIDWORKS integration and assembly review. |
| Does a STEP upload replace a SOLIDWORKS part? | No. It is a separate file; native-part or assembly integration requires an explicit CAD change. |
| Can I run Start_CAD.bat on Mac? | Use Start_CAD.command instead. |

## Official download links

- [Homebrew](https://brew.sh/)
- [Python for macOS](https://www.python.org/downloads/macos/)
- [Git LFS](https://git-lfs.com/)
- [GitHub CLI installation](https://github.com/cli/cli/blob/trunk/docs/install_macos.md)
- [TVR CAD repository](https://github.com/YoussefMorkous/TVR-MECH-CAD-REPO)

## GitHub words you will see

- **Repository:** the team's files and their change history.
- **Clone:** your local download of the repository.
- **Scope:** the files your current edit is allowed to change.
- **Pull request:** your submitted changes waiting for lead review.
- **Merge:** accepting a pull request into the approved team design.
- **main:** the branch containing approved files.
- **Git LFS:** the storage tool for large files, including STEP and SOLIDWORKS files.
- **Lock:** a reservation that prevents overlapping edits within a project when members follow this workflow.
