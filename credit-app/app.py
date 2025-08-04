import streamlit as st
import pandas as pd
import pdfplumber
import collections
import re

# --- 輔助函數 ---
def normalize_text(cell_content):
    """
    標準化從 pdfplumber 提取的單元格內容。
    處理 None 值、pdfplumber 的 Text 物件和普通字串。
    將多個空白字元（包括換行）替換為單個空格，並去除兩端空白。
    """
    if cell_content is None:
        return ""

    text = ""
    if hasattr(cell_content, 'text'):
        text = str(cell_content.text)
    elif isinstance(cell_content, str):
        text = cell_content
    else:
        text = str(cell_content)
    
    # 將所有空白字元替換為單個空格，並去除前後空白
    return re.sub(r'\s+', ' ', text).strip()

def make_unique_columns(columns_list):
    """
    將列表中的欄位名稱轉換為唯一的名稱，處理重複和空字串。
    如果遇到重複或空字串，會添加後綴 (例如 'Column_1', '欄位_2')。
    """
    seen = collections.defaultdict(int)
    unique_columns = []
    for col in columns_list:
        # 清理欄位名稱，移除多餘空格和特殊符號
        original_col_cleaned = normalize_text(col)
        
        # 如果清理後還是空的，給個通用名稱
        if not original_col_cleaned:
            # 優先使用偵測到的Column_X，然後再遞增
            column_name_base = "Column_"
            current_idx = 1
            while f"{column_name_base}{current_idx}" in unique_columns:
                current_idx += 1
            name = f"{column_name_base}{current_idx}"
        else:
            name = original_col_cleaned
        
        # 檢查是否已存在，並生成唯一名稱
        counter = seen[name]
        final_name = name
        while final_name in unique_columns: # 避免生成 Column_1_1, 而直接 Column_2
            counter += 1
            final_name = f"{name}_{counter}" if counter > 1 else name
        
        # 確保最終名稱真的是唯一的，因為存在 Column_1, Column_1_1, Column_1_2 的情況
        # 如果 name 本身是 Column_X 形式，則直接使用新的唯一數字
        if re.match(r"Column_\d+", name) and counter > 0:
            current_col_num = int(name.split('_')[-1]) if name.split('_')[-1].isdigit() else 0
            final_name = f"Column_{max(current_col_num, len(unique_columns)) + 1}"
            while final_name in unique_columns:
                final_name = f"Column_{int(final_name.split('_')[-1]) + 1}"
        elif counter > 0:
            final_name = f"{name}_{counter}"
        
        unique_columns.append(final_name)
        seen[name] = counter 

    return unique_columns


def calculate_total_credits(df_list):
    """
    從提取的 DataFrames 列表中計算總學分。
    尋找包含 '學分' 或 '學分(GPA)' 類似字樣的欄位進行加總。
    """
    total_credits = 0.0
    
    st.subheader("學分計算分析")

    # 定義可能的學分欄位名稱關鍵字
    credit_column_keywords = ["學分", "學分數", "學分(GPA)", "學 分", "Credits"] 
    
    # 用於從可能包含GPA的字符串中提取數字學分，例如 "A 2" -> 2, "3" -> 3
    # 尋找字串中所有可能的數字 (整數或浮點數)，並取最後一個（通常是學分）
    credit_pattern = re.compile(r'(\d+(\.\d+)?)') 

    for df_idx, df in enumerate(df_list):
        st.write(f"--- 分析表格 {df_idx + 1} ---")
        st.write(f"偵測到的原始欄位名稱: `{list(df.columns)}`") 
        
        found_credit_column = None
        
        # 優先匹配明確的學分關鍵字
        for col in df.columns:
            cleaned_col_for_match = "".join(char for char in col if '\u4e00' <= char <= '\u9fa5' or 'a' <= char <= 'z' or 'A' <= char <= 'Z' or '0' <= char <= '9').strip()
            if any(keyword in cleaned_col_for_match for keyword in credit_column_keywords):
                found_credit_column = col 
                break
        
        # 如果沒有明確匹配，嘗試從通用名稱 (Column_X) 中猜測學分欄位
        if not found_credit_column:
            # 尋找可能包含數字的 Column_X 欄位
            potential_credit_columns = []
            for col in df.columns:
                if re.match(r"Column_\d+", col):
                    # 檢查該欄位的前幾行數據是否大部分是數字或可轉換為數字
                    # 取前5行數據進行判斷，避免空行或表尾總計的干擾
                    sample_data = df[col].head(5).apply(normalize_text).tolist()
                    numeric_count = 0
                    for item_str in sample_data:
                        if item_str == "通過" or item_str == "抵免":
                            numeric_count += 1
                        else:
                            matches = credit_pattern.findall(item_str)
                            if matches:
                                try:
                                    float(matches[-1][0])
                                    numeric_count += 1
                                except ValueError:
                                    pass
                    
                    # 如果超過一半的樣本數據是數字，則認為可能是學分欄位
                    if len(sample_data) > 0 and numeric_count / len(sample_data) > 0.5:
                        potential_credit_columns.append(col)
            
            # 如果找到多個潛在學分欄位，嘗試找出最像學分的
            # 通常學分會在科目名稱後面幾欄
            if potential_credit_columns:
                # 找到科目名稱欄位，學分欄位應該在其右側
                subject_name_col_idx = -1
                for i, col in enumerate(df.columns):
                    if "科目名稱" in normalize_text(col):
                        subject_name_col_idx = i
                        break
                
                if subject_name_col_idx != -1:
                    # 選取科目名稱右側且最接近的潛在學分欄位
                    for p_col in potential_credit_columns:
                        if df.columns.get_loc(p_col) > subject_name_col_idx:
                            found_credit_column = p_col
                            break
                
                # 如果沒有科目名稱欄位或右側沒有，就選第一個潛在學分欄位
                if not found_credit_column and potential_credit_columns:
                    found_credit_column = potential_credit_columns[0]


        if found_credit_column:
            st.info(f"從表格 {df_idx + 1} (原始欄位: '{found_credit_column}') 偵測到學分數據。")
            try:
                processed_credits = []
                for item in df[found_credit_column]:
                    item_str = normalize_text(item) # 使用標準化函數處理數據單元格
                    
                    credit_val = 0.0
                    # 優先處理已知非數字的學分情況
                    if item_str == "通過" or item_str == "抵免":
                        credit_val = 0.0
                    else:
                        # 嘗試用正則表達式從字串中提取所有數字
                        matches = credit_pattern.findall(item_str)
                        if matches:
                            # 假設最後一個數字通常是學分，例如 "A 2" 中的 "2"
                            try:
                                credit_val = float(matches[-1][0]) 
                            except ValueError:
                                credit_val = 0.0
                        else:
                            credit_val = 0.0 # 沒有匹配到數字
                    
                    processed_credits.append(credit_val)

                credits_series = pd.Series(processed_credits)
                
                valid_credits = credits_series[credits_series >= 0] 
                
                current_table_credits = valid_credits.sum()
                total_credits += current_table_credits
                st.write(f"表格 {df_idx + 1} 的學分總計: **{current_table_credits:.2f}**")
                
            except Exception as e:
                st.warning(f"表格 {df_idx + 1} 的學分欄位 '{found_credit_column}' 轉換為數值時發生錯誤: `{e}`")
                st.warning("該表格的學分可能無法計入總數。請檢查學分欄位數據是否為純數字或可提取數字。")
        else:
            st.info(f"表格 {df_idx + 1} 未偵測到明確的學分欄位。檢查欄位：`{list(df.columns)}`。不計入總學分。")
            
    return total_credits

def process_pdf_file(uploaded_file):
    """
    使用 pdfplumber 處理上傳的 PDF 檔案，提取表格。
    """
    all_grades_data = []

    try:
        with pdfplumber.open(uploaded_file) as pdf:
            st.write(f"正在處理檔案: **{uploaded_file.name}**")
            num_pages = len(pdf.pages)
            st.info(f"PDF 總頁數: **{num_pages}**")

            for page_num, page in enumerate(pdf.pages):
                st.subheader(f"頁面 {page_num + 1}")

                table_settings = {
                    "vertical_strategy": "lines",
                    "horizontal_strategy": "lines",
                    "snap_tolerance": 3,
                    "join_tolerance": 3,
                    "edge_min_length": 3,
                    "text_tolerance": 1,
                    # 可以嘗試調整這些參數來優化表格偵測
                    # "intersection_tolerance": 5, 
                    # "min_words_vertical": 1, 
                    # "min_words_horizontal": 1,
                }
                
                current_page = page
                
                # --- 針對特定 PDF 和頁面進行 bbox 調整 ---
                # **重要：您需要根據實際PDF內容，手動測量精確的bbox坐標**
                # 坐標格式為 (x0, y0, x1, y1)
                # x0, y0 是左上角坐標，x1, y1 是右下角坐標
                # 您可以使用 PDF 閱讀器的「量測工具」或 pdfplumber 的 debug 模式來獲取這些坐標
                if "謝云瑄成績總表.pdf" in uploaded_file.name:
                    if page_num + 1 == 3: # 謝云瑄成績總表.pdf 的第 3 頁
                        # 範例坐標，請替換為您測量到的精確值
                        # 建議您嘗試較大的範圍，然後逐步縮小
                        st.warning(f"請為謝云瑄成績總表.pdf 頁面 {page_num + 1} 提供精確的 bbox 坐標 (x0, y0, x1, y1)。")
                        # current_page = page.crop((x0, y0, x1, y1)) 
                    elif page_num + 1 == 4: # 謝云瑄成績總表.pdf 的第 4 頁
                        # 範例坐標，請替換為您測量到的精確值
                        st.warning(f"請為謝云瑄成績總表.pdf 頁面 {page_num + 1} 提供精確的 bbox 坐標 (x0, y0, x1, y1)。")
                        # current_page = page.crop((x0, y0, x1, y1))
                # --- 結束 bbox 調整 ---

                try:
                    tables = current_page.extract_tables(table_settings)

                    if not tables:
                        st.warning(f"頁面 **{page_num + 1}** 未偵測到表格。這可能是由於 PDF 格式複雜或表格提取設定不適用。")
                        continue

                    for table_idx, table in enumerate(tables):
                        st.markdown(f"**頁面 {page_num + 1} 的表格 {table_idx + 1}**")
                        
                        processed_table = []
                        for row in table:
                            normalized_row = [normalize_text(cell) for cell in row]
                            processed_table.append(normalized_row)
                        
                        if not processed_table:
                            st.info(f"表格 **{table_idx + 1}** 提取後為空。")
                            continue

                        # 假設第一行是標題行，但確保有足夠的行
                        if len(processed_table) > 0:
                            header_row = processed_table[0]
                            data_rows = processed_table[1:]
                        else:
                            header_row = []
                            data_rows = []

                        unique_columns = make_unique_columns(header_row)

                        if data_rows:
                            num_columns_header = len(unique_columns)
                            cleaned_data_rows = []
                            for row in data_rows:
                                if len(row) > num_columns_header:
                                    cleaned_data_rows.append(row[:num_columns_header])
                                elif len(row) < num_columns_header:
                                    cleaned_data_rows.append(row + [''] * (num_columns_header - len(row)))
                                else:
                                    cleaned_data_rows.append(row)

                            try:
                                df_table = pd.DataFrame(cleaned_data_rows, columns=unique_columns)
                                all_grades_data.append(df_table)
                                st.dataframe(df_table)
                            except Exception as e_df:
                                st.error(f"頁面 {page_num + 1} 表格 {table_idx + 1} 轉換為 DataFrame 時發生錯誤: `{e_df}`")
                                st.error(f"原始處理後數據範例: {processed_table[:2]} (前兩行)")
                                st.error(f"生成的唯一欄位名稱: {unique_columns}")
                        else:
                            st.info(f"表格 **{table_idx + 1}** 沒有數據行。")

                except Exception as e_table:
                    st.error(f"頁面 **{page_num + 1}** 處理表格時發生錯誤: `{e_table}`")
                    st.warning("這可能是由於 PDF 格式複雜或表格提取設定不適用。")

    except pdfplumber.PDFSyntaxError as e_pdf_syntax:
        st.error(f"處理 PDF 語法時發生錯誤: `{e_pdf_syntax}`。檔案可能已損壞或格式不正確。")
    except Exception as e:
        st.error(f"處理 PDF 檔案時發生一般錯誤: `{e}`")
        st.error("請確認您的 PDF 格式是否為清晰的表格。若問題持續，可能是 PDF 結構較為複雜，需要調整 `pdfplumber` 的表格提取設定。")

    return all_grades_data

# --- Streamlit 應用主體 ---
def main():
    st.set_page_config(page_title="PDF 成績單提取與學分計算工具", layout="wide")
    st.title("📄 PDF 成績單表格數據提取與學分計算")

    st.write("請上傳您的 PDF 成績單檔案，工具將嘗試提取其中的表格數據並計算總學分。")

    uploaded_file = st.file_uploader("選擇一個 PDF 檔案", type="pdf")

    if uploaded_file is not None:
        st.success(f"已上傳檔案: **{uploaded_file.name}**")
        with st.spinner("正在處理 PDF，請稍候..."):
            extracted_dfs = process_pdf_file(uploaded_file)

        if extracted_dfs:
            st.success("成功提取所有表格數據！")
            st.write("以下是所有提取到的表格數據 (每個表格作為一個 DataFrame)：")
            
            try:
                # 嘗試將所有 DataFrame 合併，如果欄位名稱不一致，會導致 NaN
                combined_df = pd.concat(extracted_dfs, ignore_index=True)
                st.subheader("所有歷年成績表格合併後的數據 (若結構相容)")
                st.dataframe(combined_df)
                
                # 計算總學分
                total_credits = calculate_total_credits(extracted_dfs)
                st.markdown(f"## 總計學分: **{total_credits:.2f}**")
                st.info("請注意：學分計算是基於偵測到的「學分」欄位加總，並排除「抵免」、「通過」等非數字或非正數學分。")

                # 提供下載選項
                csv_data = combined_df.to_csv(index=False, encoding='utf-8-sig')
                st.download_button(
                    label="下載所有數據為 CSV",
                    data=csv_data,
                    file_name=f"{uploaded_file.name.replace('.pdf', '')}_extracted_data.csv",
                    mime="text/csv",
                )
            except Exception as e_concat:
                st.warning(f"無法將所有提取的表格合併：`{e_concat}`。這通常是因為不同表格的欄位結構或數量不一致。")
                st.info("每個單獨的表格已在上方獨立顯示，您可以查看單獨的表格結果。")
                # 即使合併失敗，也嘗試計算學分
                total_credits = calculate_total_credits(extracted_dfs)
                st.markdown(f"## 總計學分: **{total_credits:.2f}**")
                st.info("請注意：學分計算是基於偵測到的「學分」欄位加總，並排除「抵免」、「通過」等非數字或非正數學分。")
        else:
            st.warning("未從 PDF 中提取到任何表格數據。請檢查 PDF 內容或嘗試調整 `table_settings`。")
    else:
        st.info("請上傳 PDF 檔案以開始處理。")

if __name__ == "__main__":
    main()
