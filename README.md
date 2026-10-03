# TVR CAD Vault

Select a project in the Windows helper, work on its complete assembly, and submit changes for lead review.
The existing rocket stays in `cad/`; new projects have separate folders under `cad/projects/<project-id>/`. Projects share `main` and Git history; they are not separate Git branches.

## Member workflow

1. Open `Start_CAD.bat`. Choose a **Project** at the top. Click **Refresh projects** to fetch newly approved projects before starting an edit. Select the parts you intend to edit and click **Start edit**.
2. Open the assembly from the **Assembly folder** shown in the helper, in SOLIDWORKS 2026. Edit, rebuild, and save parts and parent assemblies.
3. Click **Submit for review**. The helper detects changed bytes, checks the selected scope, and opens a GitHub pull request.
4. Youssef reviews the complete assembly and merges the pull request.
5. Click **Finish after merge / closure** to release the locks.

One whole-assembly edit session is allowed **per project**. Parent `.SLDASM` files in that project are automatically in scope. Different members can edit different projects independently. Each local clone handles one edit session at a time; finish or cancel it before switching projects. The project selector stays disabled while a local session exists.

For the selected project, the helper shows **Currently being edited by...** with the lock owner's name and elapsed time. It refreshes from the lock server every minute and when you perform an action. Viewing and **Download current / historic snapshot** remain available during another person's edit; a download alone never takes a lock. An unavailable lock server is shown as an unknown status, rather than claiming the vault is free.

If you decide not to submit, close SOLIDWORKS and click **Cancel edit (keep backup)**. It saves a complete ZIP of the selected project in `exports/`, stashes staged/unstaged and untracked Git work, and retains the edit branch and a recovery JSON with the ZIP paths and stash IDs. It closes any PR for that session before releasing selected locks, then releases the assembly lock last. If closure, backup, or unlocking fails, locks/session information remain for a retry. Cancellation does not delete your branch or backups. Start a fresh edit from current `main` before reconciling recovered work.

Sessions become **overdue after 24 hours**. **Actions → Overdue CAD edit reminders** checks daily at 16:00 UTC (and supports Run workflow). It opens one GitHub issue per overdue session and mentions the repository owner/lead, Youssef. Notifications follow your GitHub notification settings. The helper also warns the editor while it is open. Because the server check is daily, the first issue may appear between 24 and 48 hours after checkout, subject to GitHub scheduling delays. The issue closes after that lock is released; manually closing it acknowledges the reminder without generating duplicates. Neither the reminder nor closing its issue releases a lock. No automatic expiry is enabled.

For download/edit/upload: start an edit, **Export editable ZIP**, extract to a separate folder, edit and save there, ZIP the `cad/` folder itself, and **Import returned ZIP**. Use the same filenames and directory layout. Import expects the complete selected project, not just changed parts. Keep the exported `cad/projects/<project-id>/` structure and `_project.json` for new projects. Files from another project are rejected before anything is overwritten. Missing selected files count as deletions. Extend scope explicitly before importing new or unexpected files. A pre-import ZIP backup is saved in `exports/`.

## One-time member installation (Windows)

Install Git for Windows (with Git LFS), GitHub CLI, and Python 3 with Tcl/Tk and the `py` launcher. Sign in to GitHub CLI once with `gh auth login`, then clone this repository using your normal GitHub access:

```powershell
gh repo clone YoussefMorkous/TVR-MECH-CAD-REPO
cd TVR-MECH-CAD-REPO
Start_CAD.bat
```

Click **One-time setup**. Every editor needs repository write access and their own GitHub account. Give Git a name and email if it asks at the first commit. Keep the clone outside OneDrive or similar synced folders. Close SOLIDWORKS before switching snapshots or starting another session. Never open a historic snapshot and the current assembly with identical filenames in the same SOLIDWORKS session.

## Add a project and import its initial assembly

Any member with repository write access can create a project through the helper. The lead still reviews and merges its initial import.

1. Close SOLIDWORKS and finish/cancel any current session.
2. In SOLIDWORKS, use **File → Pack and Go** on the complete assembly. Save to a separate folder outside the repository. If you received a ZIP, extract it first. Include referenced parts, hardware, drawings, design tables and dependencies; preserve folder structure.
3. Open `Start_CAD.bat` and click **Add project + import assembly**.
4. Enter a display name, for example **Cage testing frames**.
5. Accept or edit the suggested unique folder ID, for example `cage-testing-frames`. IDs use lowercase letters, numbers and hyphens. `legacy` is reserved for the existing rocket.
6. Choose the unzipped Pack and Go folder containing the `.SLDASM` assembly.
7. The helper creates the project, starts its import session, and selects it. Open the top-level assembly from the **Assembly folder** shown in the helper. Confirm all references resolve inside this project, rebuild and save.
8. Click **Submit for review**. After the lead checks the assembly and merges its PR, click **Finish after merge / closure**.
9. Other members click **Refresh projects** to get it in their project selector.

Each project must contain its own dependencies. Do not reference another project's working files; projects can be edited independently. Same filenames may exist in separate project folders. Never open assemblies with identical component names from different projects in the same SOLIDWORKS session.

The **Import initial assembly** button is for an empty selected project only. Existing assemblies are updated through **Start edit**.

## Update an existing installation

All members should update the helper before using projects. Finish or cancel any current edit, close SOLIDWORKS and the helper, then in GitHub Desktop select this repository, switch to **main**, click **Fetch origin**, then **Pull origin** when offered. Reopen `Start_CAD.bat`. The current rocket appears as **TVR Rocket (existing assembly) [legacy]** with its files and references in their original location. Old local sessions without a project ID remain associated with this rocket.

## Admin setup

The deployed repository currently uses a `main` protection rule requiring a pull request, one approval, CODEOWNERS review, dismissal of stale approvals, and the current `CAD snapshot` check. Force pushes and deletion are disabled. The repository owner retains GitHub's administrator bypass for the initial import and lead-authored changes, which cannot receive the owner's own approval. Use it only after checking the assembly and passing CI.

The repository is currently public. GitHub Free only enforces these rules for public repositories. Making it private on this plan removes enforcement; decide on visibility and plan before importing non-public CAD.

The required review check is **CAD snapshot**. Where your GitHub plan permits private-repository branch protection, protect `main`, require this check and a CODEOWNERS approval, dismiss stale approvals, require the branch to be current before merging, and disallow force pushes and deletions. Give only the lead release/admin authority. Apply tag rules to `V*` where supported.

CODEOWNERS alone does not enforce approval. If your account cannot protect a private repository, these are team rules and the helper checks, not an access-control guarantee: members with write access can bypass them. Do not call the vault protected until GitHub settings are verified. The connected GitHub app may not have administration permission to configure those settings.

Locks also depend on members using this helper/Git LFS and not disabling verification. The helper acquires the selected project's LFS marker lock plus selected existing native CAD files and assemblies. It rechecks ownership before submission and retains locks through review. The existing rocket uses `cad/.edit-lock`; new projects use `cad/projects/<project-id>/.edit-lock`. Updates are scoped to one project and cannot include another project's files, even if someone lists them as allowed in the manifest. SHA-256 compares file bytes, not geometry; a SOLIDWORKS save or metadata change may count as a change.

## Reviews and history

Each accepted edit creates a commit and a `changes/<session>.json` record containing the project ID, review base commit, reason, allowed paths, and actual additions/modifications/deletions. The GitHub pull request lists changed files and preserves the discussion. Any commit identifies a complete snapshot, including unchanged files.

**Download current / historic snapshot** accepts `origin/main`, a tag such as `V1.85.2`, or a full commit SHA. It reconstructs the selected project at that snapshot and fetches real LFS bytes into a separate ZIP without changing the editing workspace. Native filenames stay stable.

To find snapshots containing a specific component's edits, browse its GitHub file history or use:

```powershell
git log --oneline -- cad/Parts/TVR-2310_MotorMount.SLDPRT
```

Do not use a generic GitHub source ZIP as your CAD download: it may contain LFS pointers rather than real files. Use the helper or the custom release asset.

## Releases

After reviewing and rebuilding the complete assembly on `main`, open **Actions → Publish reviewed CAD release → Run workflow**. Use `main`, enter `V1.85.2` or `V2.0`, paste the full reviewed commit SHA (`git rev-parse origin/main` after fetching), and confirm your review. The workflow stops if main advanced since that review. This existing release workflow archives **all projects together**. It publishes a new tag, a full `TVR-<version>.zip` asset, and a SHA-256 inventory, and refuses to replace an existing tag. Normal accepted edits are commits; only validated assemblies get a release number.

Git/LFS stores another complete binary object for each changed file and reuses unchanged objects. Release ZIPs are additional full archives for convenient downloads; they are not the deduplicated backing store. Monitor LFS storage and download bandwidth in GitHub billing.

## Filenames, variants and references

- Keep identities stable, for example `TVR-2310_MotorMount.SLDPRT`. Release numbers live on tags.
- Use SOLIDWORKS configurations for intentionally supported variants where appropriate. Record the target motor/configuration in the change reason.
- An independently maintained design can get a new part number. Git branches preserve V1/V2 history, but CAD files still cannot be automatically merged.
- Preserve all dependencies inside the selected project folder. Git snapshots preserve paths and bytes, but cannot guarantee SOLIDWORKS reference resolution, mates, or geometry.
- Review checks verify manifests and native CAD LFS pointers. They do not run SOLIDWORKS, generate Pack and Go, parse dependencies, produce previews, or validate manufacture/flight suitability.
- Viewing uses reviewed `previews/` files. A read-only flag on downloaded native CAD is a convenience, not DRM.

## Recovery

If the network fails after commit or push, **Submit for review** can be retried; the helper records its stage and reuses an existing PR. If unlocking fails, **Finish** retains the remaining IDs and can be retried. If `main` advances only in other projects or tooling, **Submit for review** merges the latest main into your branch and updates the manifest base without force pushing. This can also update an already open PR: click Submit again if it needs to catch up after another project merges. If your selected project changed on main, submission stops and retains your work and locks. If your own PR was merged, click Finish; otherwise ask the lead to reconcile the project. An interrupted review-base update is journaled locally; retry Submit to complete it, or Cancel to preserve and close the session.

For an abandoned edit, use **Cancel edit (keep backup)**, or `py -3 tools/cad.py cancel` after closing SOLIDWORKS. If interruption leaves the session in `canceling`, retry Cancel; Submit and Finish will not skip that recovery. The recovery JSON in `exports/` records the retained branch, commit, ZIP paths, and stash IDs. To inspect recovered work later, preserve the current workspace first and apply the recorded stash with `git stash apply --index <stash-id>` on its original branch, or extract its ZIP into a separate folder. Do not apply old work over an active session without lead reconciliation.

If the original editor is unavailable, the lead first confirms that their work is preserved and closes their pending CAD PR. Inspect `git lfs locks --json`, then use `git lfs unlock --id <selected-file-lock-id> --force` for each selected lock belonging to that abandoned session and finally its **own project marker lock** ID (`cad/.edit-lock` for the existing rocket, or `cad/projects/<project-id>/.edit-lock` for a new project). Server permission is required. Never release the project marker first or blindly unlock every team member's files. A previously downloaded copy still exists; the original editor must start a new session against current main and reconcile it before submitting.

## Command-line equivalents

```powershell
py -3 tools/cad.py setup
py -3 tools/cad.py start --reason "Increase clearance for motor configuration X" cad/Parts/TVR-2310_MotorMount.SLDPRT
py -3 tools/cad.py seed "C:\PackAndGo\V2" --project v2 --name "V2"
py -3 tools/cad.py start --project v2 --reason "Update V2 bracket" cad/projects/v2/Bracket.SLDPRT
py -3 tools/cad.py status
py -3 tools/cad.py allow cad/Parts/AdditionalPart.SLDPRT
py -3 tools/cad.py submit
py -3 tools/cad.py finish
py -3 tools/cad.py cancel
py -3 tools/cad.py export old-rocket.zip --ref V1.85.2 --project legacy
py -3 tools/cad.py export current-v2.zip --ref origin/main --project v2
```

## Reference documentation

- [Git LFS locking](https://github.com/git-lfs/git-lfs/blob/main/docs/man/git-lfs-lock.adoc)
- [Git LFS lock verification](https://github.com/git-lfs/git-lfs/blob/main/docs/man/git-lfs-locks.adoc)
- [Protected branch availability and settings](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches)
- [LFS objects in GitHub source archives](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/managing-repository-settings/managing-git-lfs-objects-in-archives-of-your-repository)
