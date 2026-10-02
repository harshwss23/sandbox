---
description: Step 1 - unpack the zip they uploaded into the workspace
---

Unpack the contributor's uploaded archive: $ARGUMENTS

```bash
python3 ~/flc/bin/unpack_upload.py $ARGUMENTS
```

Run it with no arguments unless they named a specific file. It finds the
archive in `environment/workspace/`, unpacks it there, deletes the archive, and
clears out the `__MACOSX` folder and `.DS_Store` files the operating system put
in it. If everything in the archive was inside a single folder, it lifts the
contents up a level, because the workspace itself is what the model sees as
`/workspace` and a wrapper folder puts their files one step deeper than their
prompt describes.

It prints the resulting layout. Read it back to them and confirm it looks like
what they intended -- this is the one moment where a wrong folder structure is
easy to put right, and it is invisible later.

If it reports the archive is somewhere other than the workspace, it says so and
gives the command with the right filename; just run that.

Do not reorganise, rename or tidy their files afterwards. The layout is part of
the task: a folder that looks like a real working folder is what makes the task
measure anything, and what looks untidy to you is often the point. The only
structural change to make is the wrapper-folder lift, which the script already
handles.

If they have more material to add later, they can upload another zip and run
this again -- it unpacks alongside what is already there.

Then point them at step 2: write the question in `prompt.md`, then
`/flc-prompt-check`, then `/flc-check-inputs`.
