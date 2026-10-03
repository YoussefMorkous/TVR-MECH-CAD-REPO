# TVR CAD Vault

One stable CAD directory, complete assembly snapshots, and lead review before changes become current.
This repository is separate from the team's existing projects.

## Member workflow

1. Open `Start_CAD.bat`. Select the parts you intend to edit and click **Start edit**.
2. Open the assembly inside this clone's `cad/` directory in SOLIDWORKS 2026. Edit, rebuild, and save parts and parent assemblies.
3. Click **Submit for review**. The helper detects changed bytes, checks the selected scope, and opens a GitHub pull request.
4. Youssef reviews the complete assembly and merges the pull request.
5. Click **Finish after merge / closure** to release the locks.

One whole-assembly edit session is allowed at a time. All parent `.SLDASM` files are automatically in scope. This deliberately avoids combining two independently saved binary assemblies. Per-component parallel sessions can be added later with a proper integration process.

The helper shows **Currently being edited by...** with the lock owner's name and elapsed time. It refreshes from the lock server every minute and when you perform an action. Viewing and **Download current / historic snapshot** remain available during another person's edit; a download alone never takes a lock. An unavailable lock server is shown as an unknown status, rather than claiming the vault is free.

If you decide not to submit, close SOLIDWORKS and click **Cancel edit (keep backup)**. It saves a complete CAD ZIP in `exports/`, stashes staged/unstaged and untracked Git work, and retains the edit branch and a recovery JSON with the ZIP paths and stash IDs. It closes any PR for that session before releasing selected locks, then releases the assembly lock last. If closure, backup, or unlocking fails, locks/session information remain for a retry. Cancellation does not delete your branch or backups. Start a fresh edit from current `main` before reconciling recovered work.

Sessions become **overdue after 24 hours**. **Actions → Overdue CAD edit reminders** checks daily at 16:00 UTC (and supports Run workflow). It opens one GitHub issue per overdue session and mentions the repository owner/lead, Youssef. Notifications follow your GitHub notification settings. The helper also warns the editor while it is open. Because the server check is daily, the first issue may appear between 24 and 48 hours after checkout, subject to GitHub scheduling delays. The issue closes after that lock is released; manually closing it acknowledges the reminder without generating duplicates. Neither the reminder nor closing its issue releases a lock. No automatic expiry is enabled.

For download/edit/upload: start an edit, **Export editable ZIP**, extract to a separate folder, edit and save there, ZIP the `cad/` folder itself, and **Import returned ZIP**. Use the same filenames and directory layout. Import expects a complete snapshot, not just changed parts. Missing selected files count as deletions. Extend scope explicitly before importing new or unexpected files. A pre-import ZIP backup is saved in `exports/`.

## One-time member installation (Windows)

Install Git for Windows (with Git LFS), GitHub CLI, and Python 3 with Tcl/Tk and the `py` launcher. Sign in to GitHub CLI once with `gh auth login`, then clone this repository using your normal GitHub access:

```powershell
gh repo clone YoussefMorkous/TVR-MECH-CAD-REPO
cd TVR-MECH-CAD-REPO
Start_CAD.bat
```

Click **One-time setup**. Every editor needs repository write access and their own GitHub account. Give Git a name and email if it asks at the first commit. Keep the clone outside OneDrive or similar synced folders. Close SOLIDWORKS before switching snapshots or starting another session. Never open a historic snapshot and the current assembly with identical filenames in the same SOLIDWORKS session.

## Initial import (Youssef)

Create a SOLIDWORKS **Pack and Go folder** of your current full assembly. Preserve its folder structure, include required hardware, drawings, design tables, and other dependencies, and choose one consistent SOLIDWORKS version for the team. Avoid references to parts outside the package. Do not flatten filenames if duplicates exist.

Click **Import initial assembly (lead)** and choose that separate folder. Open the imported assembly from `cad/`, confirm it resolves without outside files, rebuild and save, then **Submit for review**. Merge this initial pull request and finish the session. After that, members can edit normally.

No actual rocket CAD files are included in the starter repository.

## Admin setup

The deployed repository currently uses a `main` protection rule requiring a pull request, one approval, CODEOWNERS review, dismissal of stale approvals, and the current `CAD snapshot` check. Force pushes and deletion are disabled. The repository owner retains GitHub's administrator bypass for the initial import and lead-authored changes, which cannot receive the owner's own approval. Use it only after checking the assembly and passing CI.

The repository is currently public. GitHub Free only enforces these rules for public repositories. Making it private on this plan removes enforcement; decide on visibility and plan before importing non-public CAD.

The required review check is **CAD snapshot**. Where your GitHub plan permits private-repository branch protection, protect `main`, require this check and a CODEOWNERS approval, dismiss stale approvals, require the branch to be current before merging, and disallow force pushes and deletions. Give only the lead release/admin authority. Apply tag rules to `V*` where supported.

CODEOWNERS alone does not enforce approval. If your account cannot protect a private repository, these are team rules and the helper checks, not an access-control guarantee: members with write access can bypass them. Do not call the vault protected until GitHub settings are verified. The connected GitHub app may not have administration permission to configure those settings.

Locks also depend on members using this helper/Git LFS and not disabling verification. The helper acquires a global LFS lock plus selected existing native CAD files and assemblies. It rechecks ownership before submission and retains locks through review. Git LFS locks are repository-wide, so this first version also serializes edits across future V2 branches. SHA-256 compares file bytes, not geometry; a SOLIDWORKS save or metadata change may count as a change.

## Reviews and history

Each accepted edit creates a commit and a `changes/<session>.json` record containing the starting assembly commit, reason, allowed paths, and actual additions/modifications/deletions. The GitHub pull request lists changed files and preserves the discussion. Any commit identifies a complete snapshot, including unchanged files.

**Download current / historic snapshot** accepts `origin/main`, a tag such as `V1.85.2`, or a full commit SHA. It reconstructs the complete tree and fetches real LFS bytes into a separate ZIP without changing the editing workspace. Native filenames stay stable.

To find snapshots containing a specific component's edits, browse its GitHub file history or use:

```powershell
git log --oneline -- cad/Parts/TVR-2310_MotorMount.SLDPRT
```

Do not use a generic GitHub source ZIP as your CAD download: it may contain LFS pointers rather than real files. Use the helper or the custom release asset.

## Releases

After reviewing and rebuilding the complete assembly on `main`, open **Actions → Publish reviewed CAD release → Run workflow**. Use `main`, enter `V1.85.2` or `V2.0`, paste the full reviewed commit SHA (`git rev-parse origin/main` after fetching), and confirm your review. The workflow stops if main advanced since that review. It publishes a new tag, a full `TVR-<version>.zip` asset, and a SHA-256 inventory, and refuses to replace an existing tag. Normal accepted edits are commits; only validated assemblies get a release number.

Git/LFS stores another complete binary object for each changed file and reuses unchanged objects. Release ZIPs are additional full archives for convenient downloads; they are not the deduplicated backing store. Monitor LFS storage and download bandwidth in GitHub billing.

## Filenames, variants and references

- Keep identities stable, for example `TVR-2310_MotorMount.SLDPRT`. Release numbers live on tags.
- Use SOLIDWORKS configurations for intentionally supported variants where appropriate. Record the target motor/configuration in the change reason.
- An independently maintained design can get a new part number. Git branches preserve V1/V2 history, but CAD files still cannot be automatically merged.
- Preserve all dependencies inside `cad/`. Git snapshots preserve paths and bytes, but cannot guarantee SOLIDWORKS reference resolution, mates, or geometry.
- Review checks verify manifests and native CAD LFS pointers. They do not run SOLIDWORKS, generate Pack and Go, parse dependencies, produce previews, or validate manufacture/flight suitability.
- Viewing uses reviewed `previews/` files. A read-only flag on downloaded native CAD is a convenience, not DRM.

## Recovery

If the network fails after commit or push, **Submit for review** can be retried; the helper records its stage and reuses an existing PR. If unlocking fails, **Finish** retains the remaining IDs and can be retried. If `main` advances while a session is open, submission stops: keep/export your work and have the lead reconcile it instead of overwriting newer files.

For an abandoned edit, use **Cancel edit (keep backup)**, or `py -3 tools/cad.py cancel` after closing SOLIDWORKS. If interruption leaves the session in `canceling`, retry Cancel; Submit and Finish will not skip that recovery. The recovery JSON in `exports/` records the retained branch, commit, ZIP paths, and stash IDs. To inspect recovered work later, preserve the current workspace first and apply the recorded stash with `git stash apply --index <stash-id>` on its original branch, or extract its ZIP into a separate folder. Do not apply old work over an active session without lead reconciliation.

If the original editor is unavailable, the lead first confirms that their work is preserved and closes their pending CAD PR. Inspect `git lfs locks --json`, then use `git lfs unlock --id <selected-file-lock-id> --force` for each selected lock belonging to that abandoned session and finally its `cad/.edit-lock` ID. Server permission is required. Never release the global lock first or blindly unlock every team member's files. A previously downloaded copy still exists; the original editor must start a new session against current main and reconcile it before submitting.

## Command-line equivalents

```powershell
py -3 tools/cad.py setup
py -3 tools/cad.py start --reason "Increase clearance for motor configuration X" cad/Parts/TVR-2310_MotorMount.SLDPRT
py -3 tools/cad.py status
py -3 tools/cad.py allow cad/Parts/AdditionalPart.SLDPRT
py -3 tools/cad.py submit
py -3 tools/cad.py finish
py -3 tools/cad.py cancel
py -3 tools/cad.py export old-rocket.zip --ref V1.85.2
```

## Reference documentation

- [Git LFS locking](https://github.com/git-lfs/git-lfs/blob/main/docs/man/git-lfs-lock.adoc)
- [Git LFS lock verification](https://github.com/git-lfs/git-lfs/blob/main/docs/man/git-lfs-locks.adoc)
- [Protected branch availability and settings](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches)
- [LFS objects in GitHub source archives](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/managing-repository-settings/managing-git-lfs-objects-in-archives-of-your-repository)
