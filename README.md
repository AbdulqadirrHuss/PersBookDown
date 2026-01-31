# 📚 Personal Book Downloader

Automated ebook search and download from Library Genesis and Anna's Archive using GitHub Actions.

![GitHub Actions](https://img.shields.io/badge/GitHub%20Actions-Automated-blue)
![Python](https://img.shields.io/badge/Python-3.11-green)

## ✨ Features

- 🔍 **Dual Source Search** - Searches both LibGen and Anna's Archive
- 📖 **Format Priority** - Prefers EPUB > PDF > MOBI formats
- 🤖 **GitHub Actions** - Fully automated cloud downloads
- 📦 **Artifact Output** - Downloads available as ZIP in Actions tab
- 🔄 **Retry Logic** - Handles temporary failures gracefully

## 🚀 Quick Start

### 1. Add Books to Download

Edit `books.txt` with your desired books (one per line):

```
Title - Author
```

**Example:**
```
1984 - George Orwell
The Great Gatsby - F. Scott Fitzgerald
Dune - Frank Herbert
```

### 2. Trigger Download

**Option A: Automatic**  
Push changes to `books.txt` - workflow triggers automatically.

**Option B: Manual**  
1. Go to the **Actions** tab in your repository
2. Select **"Download Books"** workflow
3. Click **"Run workflow"** button

### 3. Get Your Books

1. After the workflow completes, go to **Actions** tab
2. Click on the completed workflow run
3. Scroll to **Artifacts** section
4. Download the **"downloaded-books"** ZIP file

## 📁 Project Structure

```
├── books.txt                    # Your book list (edit this!)
├── download_books.py            # Main automation script
├── requirements.txt             # Python dependencies
├── .gitignore                   # Ignores downloaded files
└── .github/
    └── workflows/
        └── download_books.yml   # GitHub Actions workflow
```

## 🔧 Local Usage

You can also run the script locally:

```bash
# Install dependencies
pip install -r requirements.txt

# Add books to books.txt, then run:
python download_books.py
```

Downloaded files appear in the `downloads/` folder.

## ⚠️ Troubleshooting

| Issue | Solution |
|-------|----------|
| Book not found | Check spelling, try alternative title/author |
| Mirror down | Wait and retry - mirrors change frequently |
| Wrong format | Script prioritizes EPUB/PDF; other formats may be downloaded if unavailable |
| Workflow fails | Check Actions logs for specific error messages |

## 📋 Input Format

The `books.txt` file expects entries in this format:

```
Title - Author
```

**Tips:**
- Use the exact book title for best results
- Lines starting with `#` are treated as comments
- Empty lines are ignored

## ⚖️ Disclaimer

This tool is provided for educational purposes. Users are responsible for ensuring their use complies with applicable laws and regulations in their jurisdiction.

## 📄 License

MIT License - See [LICENSE](LICENSE) for details.
