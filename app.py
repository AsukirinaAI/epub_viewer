from flask import Flask, render_template, request, jsonify, send_file
import os
import json
import zipfile
import re
from bs4 import BeautifulSoup
import io

app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BOOKS_DIR = os.path.join(BASE_DIR, 'books')
HISTORY_FILE = os.path.join(BASE_DIR, 'history.json')
SETTINGS_FILE = os.path.join(BASE_DIR, 'reader_settings.json')

os.makedirs(BOOKS_DIR, exist_ok=True)

def load_json(filepath, default):
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return default
    return default

def save_json(filepath, data):
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def parse_epub_structure(epub_path):
    with zipfile.ZipFile(epub_path, 'r') as z:
        # Find rootfile
        container = z.read('META-INF/container.xml')
        soup = BeautifulSoup(container, 'xml')
        rootfile_path = soup.find('rootfile')['full-path']
        base_path = os.path.dirname(rootfile_path)
        
        opf_content = z.read(rootfile_path)
        opf_soup = BeautifulSoup(opf_content, 'xml')
        version = opf_soup.find('package')['version']
        items = {}
        for item in opf_soup.find_all('item'):
            items[item['id']] = item['href']
            
        spine = []
        for itemref in opf_soup.find('spine').find_all('itemref'):
            idref = itemref['idref']
            if idref in items:
                href = items[idref]
                spine.append(os.path.normpath(os.path.join(base_path, href)).replace('\\', '/'))
        
        toc_href = None
        is_ncx = True
        for item in opf_soup.find_all('item'):
            if item.get('properties') == 'nav':
                toc_href = item['href']
                is_ncx = False
                break
            elif item.get('media-type') == 'application/x-dtbncx+xml':
                toc_href = item['href']
                
        toc = []
        if toc_href:
            toc_path = os.path.normpath(os.path.join(base_path, toc_href)).replace('\\', '/')
            ncx_content = z.read(toc_path)
            
            if is_ncx:
                ncx_soup = BeautifulSoup(ncx_content, 'xml')
                for navPoint in ncx_soup.find_all('navPoint'):
                    text = navPoint.find('text').text if navPoint.find('text') else "未知章节"
                    content_src = navPoint.find('content')['src'] if navPoint.find('content') else ""
                    # Handle anchor links in src (e.g. page.xhtml#section1)
                    content_src = content_src.split('#')[0]
                    content_path = os.path.normpath(os.path.join(os.path.dirname(toc_path), content_src)).replace('\\', '/')
                    toc.append({"title": text, "src": content_path})
            else:
                # EPUB 3 Navigation Document (nav.xhtml)
                nav_soup = BeautifulSoup(ncx_content, 'html.parser')
                nav = nav_soup.find('nav', {'epub:type': 'toc'})
                if nav:
                    for a in nav.find_all('a'):
                        text = a.get_text(strip=True)
                        content_src = a.get('href', "")
                        content_src = content_src.split('#')[0]
                        content_path = os.path.normpath(os.path.join(os.path.dirname(toc_path), content_src)).replace('\\', '/')
                        toc.append({"title": text, "src": content_path})
                
        return {"spine": spine, "toc": toc, "base_path": base_path}

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/books')
def list_books():
    books = [f for f in os.listdir(BOOKS_DIR) if f.endswith('.epub')]
    return jsonify(books)

@app.route('/api/book/<filename>')
def get_book_info(filename):
    epub_path = os.path.join(BOOKS_DIR, filename)
    if not os.path.exists(epub_path):
        return jsonify({"error": "Book not found"}), 404
    info = parse_epub_structure(epub_path)
    return jsonify(info)

@app.route('/api/book/<filename>/file/<path:filepath>')
def get_book_file(filename, filepath):
    epub_path = os.path.join(BOOKS_DIR, filename)
    with zipfile.ZipFile(epub_path, 'r') as z:
        try:
            content = z.read(filepath)
            
            if filepath.endswith('.xhtml') or filepath.endswith('.html'):
                soup = BeautifulSoup(content, 'html.parser')
                
                # Replace image src
                for img in soup.find_all(['img', 'image']):
                    src = img.get('src') or img.get('xlink:href')
                    if src:
                        abs_src = os.path.normpath(os.path.join(os.path.dirname(filepath), src)).replace('\\', '/')
                        if img.name == 'img':
                            img['src'] = f"/api/book/{filename}/file/{abs_src}"
                        else:
                            img['xlink:href'] = f"/api/book/{filename}/file/{abs_src}"
                            
                for css in soup.find_all('link', rel='stylesheet'):
                    href = css.get('href')
                    if href:
                        abs_href = os.path.normpath(os.path.join(os.path.dirname(filepath), href)).replace('\\', '/')
                        css['href'] = f"/api/book/{filename}/file/{abs_href}"
                        
                content = str(soup).encode('utf-8')
                return content, 200, {'Content-Type': 'text/html; charset=utf-8'}
                
            mime_type = 'application/octet-stream'
            if filepath.endswith('.css'): mime_type = 'text/css'
            elif filepath.endswith('.jpg') or filepath.endswith('.jpeg'): mime_type = 'image/jpeg'
            elif filepath.endswith('.png'): mime_type = 'image/png'
            elif filepath.endswith('.gif'): mime_type = 'image/gif'
            elif filepath.endswith('.svg'): mime_type = 'image/svg+xml'
            
            return send_file(io.BytesIO(content), mimetype=mime_type)
        except KeyError:
            return "File not found in epub", 404

@app.route('/api/history', methods=['GET', 'POST'])
def handle_history():
    if request.method == 'GET':
        return jsonify(load_json(HISTORY_FILE, {}))
    elif request.method == 'POST':
        data = request.json
        history = load_json(HISTORY_FILE, {})
        history[data['book']] = data['position']
        save_json(HISTORY_FILE, history)
        return jsonify({"status": "success"})

@app.route('/api/settings', methods=['GET', 'POST'])
def handle_settings():
    if request.method == 'GET':
        return jsonify(load_json(SETTINGS_FILE, {"theme": "light", "show_jp": True, "font_size": 18}))
    elif request.method == 'POST':
        data = request.json
        save_json(SETTINGS_FILE, data)
        return jsonify({"status": "success"})

@app.route('/api/upload', methods=['POST'])
def upload_book():
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    if file and file.filename.endswith('.epub'):
        filepath = os.path.join(BOOKS_DIR, file.filename)
        file.save(filepath)
        return jsonify({"status": "success", "filename": file.filename})
    return jsonify({"error": "Invalid file format"}), 400

if __name__ == '__main__':
    app.run(debug=True, port=5000)
