# Seed profile pictures

One picture per employee, named by employee ID. `python seed.py` copies each one into
`static/avatars/` and points the employee at it. This folder is the local stand-in for the
SharePoint folder planned for the final build, which will hold everyone's real picture the same way.

## Using a real photo

Drop a photo in here named after the employee ID, then run `python seed.py`:

    E0005.jpg      (also .jpeg, .png, .webp or .gif, up to 5 MB)

A photo always wins over the drawing with the same ID. Leave the `.svg` where it is: it is used
again if the photo is taken away. Anyone with neither gets a generated cartoon face.

This repository is on GitHub, so only commit a photo of someone who has agreed to it.

Five demo logins already have a picture of their own in here, so there is something to see
straight after seeding: E0005 (Priya, an animated GIF), E0013 (Aisha), E0011 (Olivia),
E0004 (Emily) and E0033 (Alexander). Rename a file to another employee ID to move it, or delete
it to give that person their drawing back. Swap them for approved pictures before a real demo.

## The drawings

The `.svg` files are drawn portraits, not photos of real people, because the seeded employees
are made up. They are assigned at random and are not matched to names.

They come from "Notionists" by Zoish, released under CC0 1.0
(https://creativecommons.org/publicdomain/zero/1.0/), and were generated with DiceBear
(https://www.dicebear.com). CC0 needs no credit; it is given here so the source is on record.
