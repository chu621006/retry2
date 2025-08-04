import streamlit as st
import pandas as pd
import pdfplumber
import collections # 用於計數重複元素

# --- 輔助函數 ---
def normalize_text(cell_content):
    """
    標準化從 pdfplumber 提取的單元格內容。
    處理 None 值、pdfplumber 的 Text 物件和普通字串。
    """
    if cell_content is None:
        return ""  # 返回空字串來表示空白單元格

    # 檢查是否為 pdfplumber 的 Text 物件 (通常有 .text 屬性)
    if hasattr(cell_content, 'text'):
        return str(cell_content.text).strip()
    # 如果已經是字串
    elif isinstance(cell_content, str):
        return cell_content.strip()
    else:
        # 對於其他未知類型，嘗試轉換為字串並去除空白
        return str(cell_content).strip()

def make_unique_columns(columns_list):
    """
    將列表中的欄位名稱轉換為唯一的名稱，處理重複和空字串。
    如果遇到重複或空字串，會添加後綴 (例如 'Column_1', '欄位_2')。
    """
    seen = collections.defaultdict(int)
    unique_columns = []
    for col in columns_list:
        original_col = col if col else f"Column_{len(unique_columns) + 1}" # 為空字串提供一個初始名稱
        
        # 移除可能導致重複的特殊字元或空白 (如果需要更激進的清理)
        # cleaned_col = "".join(filter(str.isalnum, original_col)) # 只保留字母數字，可選

        name = original_col
        if seen[name] > 0:
            name = f"{original_col}_{seen[original_col]}"
        while name in unique_columns: # 再次檢查確保徹底唯一 (避免 name_1_1 的情況)
             seen[original_col] += 1
             name = f"{original_col}_{seen[original_col]}"
        
        unique_columns.append(name)
        seen[original_col] += 1 # 更新計數
    return unique_columns

def process_pdf_file(uploaded_file):
    """
    使用 pdfplumber 處理上傳的 PDF 檔案，提取表格。
    """
    all_grades_data = [] # 初始化用於儲存所有表格數據的列表

    try:
        with pdfplumber.open(uploaded_file) as pdf:
            st.write(f"正在處理檔案: **{uploaded_file.name}**")
            num_pages = len(pdf.pages)
            st.info(f"PDF 總頁數: **{num_pages}**")

            for page_num, page in enumerate(pdf.pages):
                st.subheader(f"頁面 {page_num + 1}")

                # 這裡你可以根據需要調整 table_settings
                # 對於成績單這類有清晰線條的表格，'lines' 策略通常效果不錯。
                # 如果仍有問題，可以嘗試調整容忍度或將策略改為 'text'。
                table_settings = {
                    "vertical_strategy": "lines",
                    "horizontal_strategy": "lines",
                    "snap_tolerance": 3,           # 調整線條捕捉的容忍度
                    "join_tolerance": 3,           # 調整合併線條的容忍度
                    "edge_min_length": 3,          # 最小邊緣長度，避免偵測到過短的線條
                    "text_tolerance": 1,           # 文本接近線條的容忍度
                    # 如果表格線條不明顯，可以嘗試：
                    # "vertical_strategy": "text",
                    # "horizontal_strategy": "text",
                }

                try:
                    # 嘗試提取當前頁面上的所有表格
                    tables = page.extract_tables(table_settings)

                    if not tables:
                        st.warning(f"頁面 **{page_num + 1}** 未偵測到表格。這可能是由於 PDF 格式複雜或表格提取設定不適用。")
                        continue

                    for table_idx, table in enumerate(tables):
                        st.markdown(f"**頁面 {page_num + 1} 的表格 {table_idx + 1}**")
                        
                        # 使用 normalize_text 函數處理每個單元格
                        processed_table = []
                        for row in table:
                            normalized_row = [normalize_text(cell) for cell in row]
                            processed_table.append(normalized_row)
                        
                        # DEBUG: 顯示原始處理後的表格內容，幫助理解問題
                        # st.json(processed_table) 
                        
                        if not processed_table:
                            st.info(f"表格 **{table_idx + 1}** 提取後為空。")
                            continue

                        # 處理欄位名稱
                        header_row = processed_table[0]
                        data_rows = processed_table[1:]

                        # 使用 make_unique_columns 確保欄位名稱唯一
                        unique_columns = make_unique_columns(header_row)

                        if data_rows:
                            # 確保數據行的列數與欄位名稱的列數匹配
                            # 如果不匹配，需要調整數據或欄位名稱的長度
                            # 這裡選擇截斷或填充最短的那個，以避免錯誤
                            num_columns_header = len(unique_columns)
                            # 統一所有行的長度為標題行的長度
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
    st.set_page_config(page_title="PDF 成績單提取工具", layout="wide")
    st.title("📄 PDF 成績單表格數據提取")

    st.write("請上傳您的 PDF 成績單檔案，工具將嘗試提取其中的表格數據。")

    uploaded_file = st.file_uploader("選擇一個 PDF 檔案", type="pdf")

    if uploaded_file is not None:
        st.success(f"已上傳檔案: **{uploaded_file.name}**")
        with st.spinner("正在處理 PDF，請稍候..."): # 使用 with st.spinner 確保顯示正確
            # 處理 PDF 檔案
            extracted_dfs = process_pdf_file(uploaded_file)

        if extracted_dfs:
            st.success("成功提取所有表格數據！")
            st.write("以下是所有提取到的表格數據 (每個表格作為一個 DataFrame)：")
            
            # 你可以選擇如何合併或顯示這些 DataFrame
            # 例如，將它們合併成一個大的 DataFrame (如果結構相容)
            try:
                # 嘗試將所有 DataFrame 合併，如果欄位名稱不一致，會導致 NaN
                # 這裡不再強制要求 Reindexing valid，因為我們已經處理了單個 DataFrame 的欄位唯一性
                combined_df = pd.concat(extracted_dfs, ignore_index=True)
                st.subheader("所有表格合併後的數據 (若結構相容)")
                st.dataframe(combined_df)
                
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
        else:
            st.warning("未從 PDF 中提取到任何表格數據。請檢查 PDF 內容或嘗試調整 `table_settings`。")
    else:
        st.info("請上傳 PDF 檔案以開始處理。")

if __name__ == "__main__":
    main()
