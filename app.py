import io
import re
import pandas as pd
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)
DATA_FRAME = None

def normalize_arabic(text):
    """Normalize common Arabic letter variations for accurate searching."""
    if not isinstance(text, str):
        text = str(text)
    text = re.sub(r'[\u064B-\u0652]', '', text)
    text = re.sub(r'[إأآا]', 'ا', text)
    text = re.sub(r'ة', 'ه', text)
    text = re.sub(r'ى', 'ي', text)
    return text.lower().strip()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/guide')
def guide():
    return render_template('guide.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    global DATA_FRAME
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    # Server-side: allow only common Excel-like extensions
    allowed_ext = ('.xls', '.xlsx', '.xlsm', '.xlsb', '.ods', '.csv')
    filename_lower = file.filename.lower()
    if not any(filename_lower.endswith(ext) for ext in allowed_ext):
        return jsonify({'error': 'Unsupported file type. Please upload an Excel file (xls, xlsx, xlsm, xlsb, ods, csv).'}), 400

    try:
        file_bytes = io.BytesIO(file.read())
        excel_file = pd.ExcelFile(file_bytes, engine='openpyxl')

        selected_df = None
        used_sheet_name = ""

        # Scan sheets for non-empty table data
        for sheet_name in excel_file.sheet_names:
            raw_df = pd.read_excel(excel_file, sheet_name=sheet_name, header=None)
            if not raw_df.empty and raw_df.dropna(how='all').shape[0] > 0:
                selected_df = raw_df
                used_sheet_name = sheet_name
                break

        if selected_df is None:
            return jsonify({'error': 'All sheets in this file appear completely empty.'}), 400

        # Find first row with column titles
        header_row_index = None
        for idx, row in selected_df.iterrows():
            if row.dropna().count() > 0:
                header_row_index = idx
                break

        title_row = selected_df.iloc[header_row_index]
        data_rows = selected_df.iloc[header_row_index + 1:].copy()

        # Extract non-empty headers
        valid_columns = []
        valid_indices = []

        for col_idx, cell_value in title_row.items():
            cell_str = str(cell_value).strip() if pd.notna(cell_value) else ""
            if cell_str and cell_str.lower() != 'nan' and not cell_str.startswith('Unnamed:'):
                valid_columns.append(cell_str)
                valid_indices.append(col_idx)

        if not valid_columns:
            return jsonify({'error': 'No valid column titles found.'}), 400

        data_rows = data_rows[valid_indices]
        data_rows.columns = valid_columns

        DATA_FRAME = data_rows

        return jsonify({
            'message': f"Uploaded sheet '{used_sheet_name}' successfully!",
            'columns': valid_columns,
            'total_rows': len(DATA_FRAME)
        })

    except Exception as e:
        return jsonify({'error': f'Error parsing file: {str(e)}'}), 500

@app.route('/search', methods=['POST'])
def search():
    global DATA_FRAME
    if DATA_FRAME is None:
        return jsonify({'error': 'Please upload an Excel file first.'}), 400

    data = request.json or {}
    filters = data.get('filters', [])
    mode = data.get('mode', 'AND')

    valid_filters = [f for f in filters if f.get('column') and str(f.get('query', '')).strip()]

    if not valid_filters:
        return jsonify({'results': [], 'total': 0})

    combined_mask = None

    for f in valid_filters:
        col = f['column']
        query = str(f['query']).strip()

        if col not in DATA_FRAME.columns:
            continue

        normalized_query = normalize_arabic(query)
        col_series = DATA_FRAME[col].fillna('').astype(str)
        normalized_col = col_series.apply(normalize_arabic)

        # Added regex=False to handle special characters literally and avoid PatternError
        mask = normalized_col.str.contains(normalized_query, case=False, na=False, regex=False)

        if combined_mask is None:
            combined_mask = mask
        else:
            combined_mask = (combined_mask & mask) if mode == 'AND' else (combined_mask | mask)

    if combined_mask is None:
        return jsonify({'results': [], 'total': 0})

    filtered_df = DATA_FRAME[combined_mask]
    results = filtered_df.fillna('').to_dict(orient='records')

    return jsonify({
        'results': results,
        'total': len(results),
        'columns': DATA_FRAME.columns.tolist()
    })

if __name__ == '__main__':
    app.run(debug=True, port=5000)