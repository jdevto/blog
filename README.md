# blog

dev.to article sources (`articles/`). Published via GitHub Actions to [dev.to/jajera](https://dev.to/jajera).

## Local preview

Approximate Forem/dev.to look for markdown under `articles/`:

```bash
python3 -m pip install -r preview/requirements.txt
python3 preview/preview.py
python3 preview/preview.py articles/art0146.md
python3 preview/preview.py --port 8765 articles/art0146.md
```

Default URL: [http://127.0.0.1:5477](http://127.0.0.1:5477). Use `--no-open` to skip launching a browser.
