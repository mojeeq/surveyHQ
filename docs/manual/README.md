# Manual screenshots

The pictures in `docs/susoDash-user-manual.docx`. Every one is a screenshot of a
running instance carrying a demonstration labour force survey, rather than a
mock-up, so they have to be re-captured whenever the interface changes.

To rebuild the manual:

```
pip install python-docx pillow          # build-time only, not in requirements.txt
node scripts/capture_manual.mjs \
  --url http://localhost:5173 --password '...' \
  --dashboard <dashboard id> --dataset <dataset id>
python scripts/build_manual.py
```

`capture_manual.mjs` writes the pictures here at twice the pixel size, so they
stay sharp when Word scales them onto a page; halve them before committing if
the repository is getting heavy. Two of them - `21-shared-dashboard` and
`22-password-door` - are taken through a shared link in a browser with no
account, and are captured by hand.
