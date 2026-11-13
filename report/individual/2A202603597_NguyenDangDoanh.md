# Báo cáo cá nhân — Day 6

## Dữ liệu và pipeline
- Chủ đề, nguồn/quyền, số trang và quy tắc tính trang: Sách Principle of Finance, bản LibreTexts, chương 1–3. Giấy phép CC BY 4.0. File `starter/data/100pages.pdf` gồm 100 trang vật lý; 68 trang được tính (203.691 ký tự sau chuẩn hóa). Quy tắc: tính các trang giải thích của section, kể cả Summary và Key Terms; loại front matter (tr. 1–9), chapter overview (10, 50, 83), section bài tập (44–49, 76–82) và trang chỉ còn footnote/license (<300 ký tự thân bài: 12, 18, 21, 24, 33, 36, 62). Chi tiết từng trang: `data/page_inventory.csv`; manifest: `data/manifest.csv`; script: `starter/scripts/inventory_pages.py`.
- Chuẩn hóa, lỗi và giới hạn: Đọc bằng `pypdf` 6.21.4; chuẩn hóa Unicode NFC, gộp khoảng trắng, giữ ngắt dòng; bỏ dòng header trang, khối Footnotes và câu license LibreTexts. Log: `starter/results/ingest_log.csv`. Lỗi/giới hạn đã ghi nhận:
    - Ký tự icon U+F5DC xuất hiện 17 lần trước "Learning Objectives", bị loại khi chuẩn hóa.
    - Khung "Learning Objectives" và chú thích hình bị chèn lệch thứ tự vào giữa đoạn văn; nhãn khung vẫn sót lại ở cuối trang.
    - Nhận biết đoạn văn dựa vào độ dài dòng (dòng < 110 ký tự coi là hết đoạn) là heuristic, có thể sai với bảng hoặc danh sách (ví dụ Table 2.1, Table 3.1).
- Embedding, vector store, lệnh chạy và chi phí: `sentence-transformers/all-MiniLM-L6-v2` chạy local trên CPU (sentence-transformers 6.3.0, torch 2.15.0), 384 chiều, vector chuẩn hóa L2; query và document encode giống nhau, không prefix; giới hạn 256 token (0 chunk vượt). Vector store: PostgreSQL 16.16 + pgvector 0.8.7 (Docker image `pgvector/pgvector:0.8.7-pg16`), bảng `chunks`, khoảng cách cosine (`<=>`), exact search (không tạo ANN index). Lệnh: `python -m src.run ingest`, `check-reingest`, `evaluate --split dev|test`, `export-audit`, `summarize-audit`. Chi phí: $0.
- Metadata: bắt buộc `document_id`, `source`, `page`. Bổ sung `chapter` (trường lọc), `section`, `section_title`, `page_type`, `char_start`, `char_end`, `content_hash`. Giá trị chapter/section lấy từ dòng header của chính trang đó (`X.Y.Z https://biz.libretexts.org/...`), không suy đoán. Chọn `chapter` để lọc vì cùng khái niệm xuất hiện ở nhiều chương và người dùng có thể biết trước chương mình hỏi.

## Cấu hình và benchmark
- A / B / C (tham số cụ thể, khác biệt duy nhất B–C):
  | | Chunking | Filter |
  |---|---|---|
  | A | Cửa sổ ký tự cố định 500, overlap 50, trong phạm vi 1 trang | Không |
  | B | Theo đoạn, heading gắn vào đoạn sau, gộp tối đa 800 ký tự, đoạn quá dài cắt ở cuối câu; trong phạm vi 1 trang | Không |
  | C | Dùng lại đúng index B | `chapter` = giá trị đi kèm câu hỏi, chỉ áp dụng cho câu có filter |

  A–B chỉ khác cách chunk; B–C chỉ khác việc áp filter. Cùng corpus, model, store, metric và top-k = 3. Cấu hình: `starter/src/config.py`, `artifacts/experiment_log.csv`.

- Benchmark: 20 câu trong `benchmark/questions.jsonl`: 15 dev (q01–q15: direct 4, paraphrase 4, condition 5, filter 2) và 5 test (q16–q20: direct 1, paraphrase 2, condition 1, filter 1). Test chỉ lấy từ section 1.6, 2.5, 3.3 để giảm rò rỉ. Câu filter: q04 (ch1), q11 (ch2) thuộc dev; q18 (ch3) thuộc test; filter là input giả định người dùng cung cấp trước khi truy xuất. Evidence được copy từ text đã chuẩn hóa (`scripts/dump_pages.py`) và kiểm chứng bằng `scripts/validate_benchmark.py` (20/20 quote có trên trang gold); bằng chứng thay thế ở trang Summary/Key Terms được ghi trong `alt_evidence` (q01, q02, q16).

- Tiêu chí chọn chiến lược đã chốt trước khi xem test: chọn trên dev theo thứ tự Evidence Hit@3 → Hit@1 → coherence → tài nguyên (số chunk, thời gian).


## Kết quả
| Strategy | Split | Hit@1 (n/N) | Evidence Hit@3 (n/N) | Chunk count | Thời gian | Chi phí |
|---|---|---|---|---|---|---|
| A | dev | 4/15 | 6/15 | 458 | embed ~7,1 s; search ~25 ms/câu | $0 |
| A | test | 2/5 | 2/5 | 458 | | $0 |
| B | dev | 11/15 | 12/15 | 341 | embed ~6,7 s; search ~34 ms/câu | $0 |
| B | test | 4/5 | 5/5 | 341 | | $0 |
| C | dev | 11/15 | 12/15 | 341 (dùng chung B) | không tốn thêm ingest; search ~54 ms/câu | $0 |
| C | test | 4/5 | 5/5 | 341 | | $0 |

| Strategy | Coherence trung bình /2 (n) | Metadata đủ và đúng (n/N) | Filter tuân thủ (n/N hoặc N/A) | Grounding 0/1/2 (số câu) và trung bình /2 |
|---|---|---|---|---|
| A | 0,80 (n=10) | 15/15 | dev 2/2, test 0/1 | 1 / 1 / 3 — 1,40 |
| B | 1,70 (n=10) | 15/15 | dev 2/2, test 0/1 | 0 / 0 / 5 — 2,00 |
| C | 1,70 (n=10, cùng chunk B) | 15/15 | dev 2/2, test 1/1 | 0 / 0 / 5 — 2,00 |


Đường dẫn trace, nhãn thủ công và cách chọn mẫu: trace top-3 đầy đủ (text, score, metadata, nhãn hit) ở `starter/results/traces_dev.jsonl` và `traces_test.jsonl`; chỉ số ở `metrics_dev.csv`, `metrics_test.csv`; nhãn ở `audit_coherence.csv`, `audit_metadata.csv`, `audit_grounding.csv`; tổng hợp ở `audit_summary.txt`. Coherence: 10 trang cách đều trong 68 trang được tính (11, 20, 30, 39, 54, 61, 70, 85, 93, 100), vị trí là ký tự giữa trang; quy tắc cố định trước khi xem điểm, chấm chunk chứa vị trí đó. Metadata và grounding: 5 câu test × 3 chiến lược (45 bản ghi top-3; 15 lượt grounding).


## Phân tích và kết luận
- A–B (chỉ đổi chunking): Evidence Hit@3 tăng từ 6/15 lên 12/15 (dev) và từ 2/5 lên 5/5 (test). A và B đều đưa được trang gold vào top-3 ở 14/15 câu dev, nên gần như toàn bộ chênh lệch đến từ việc **evidence bị cắt giữa hai chunk** khi chia cố định (8 câu dev, 3 câu test ở A, so với 2 câu dev ở B). Coherence tăng từ 0,80 lên 1,70; A bị 0 điểm ở vị trí 3 (mở đầu bằng "When this occurs…", mất định nghĩa disintermediation) và vị trí 5 (chỉ là mảnh Table 2.1). B cũng ít chunk hơn (341 so với 458) và ít ký tự trùng lặp hơn (193.696 so với 213.742) vì không có overlap.
- B–C (chỉ đổi filter): Hit giống hệt nhau ở cả dev và test. Trên dev, B vốn đã trả về đúng chương cho q04 và q11 nên filter không thay đổi gì. Trên test, ở q18 (inflation, chương 3), B lấy chunk thứ 2 từ trang 31 (chương 1); C thay bằng chunk chương 3, đạt tuân thủ filter 1/1 so với 0/1, nhưng top-1 vốn đã đúng nên Hit không đổi. Với corpus và bộ câu nhỏ này, filter chủ yếu giúp đảm bảo phạm vi, chưa cho thấy tăng độ chính xác.
- Ví dụ sai 1, A–q07 (dev, gold trang 52): câu "A sole proprietor has unlimited personal liability…" bị cắt ngang: chunk `p052:fixed500-50:c05` kết thúc bằng "1. A sole pro", phần còn lại nằm ở chunk sau. Top-1 là chunk ví dụ vụ kiện $500.000 trên cùng trang: đúng trang nhưng không chứa trọn evidence. B lấy trọn đoạn này ở top-1.
- Ví dụ sai 2, B–q03 (dev, gold trang 19): câu paraphrase "face to outside lenders and the public". Top-1 là định nghĩa "treasurer" ở trang Key Terms 42 (liên quan nhưng không có ý đối lập controller hướng vào trong / treasurer hướng ra ngoài); top-2 là đoạn VP-F ở trang 19, đúng trang nhưng evidence nằm ở đoạn trước. Ngoài ra, B–q02 không có trang gold nào trong top-3 ("long-lived assets" không khớp ngữ nghĩa đủ mạnh với "long-term or fixed assets"), và B–q15 có evidence nằm ở chunk ngay sau chunk được lấy (trang 89).
- Chấm tự động khắt khe hơn chấm tay: A–q18 bị tính trượt Hit@3 vì câu ví dụ "$100 bill…" bị cắt, nhưng chunk top-1 có đủ câu "Inflation means that the purchasing power of currency falls", nên grounding thủ công được 2.
- Chiến lược chọn: C. B và C hoà ở mọi tiêu chí đã chốt trên dev; chọn C vì không có câu nào kém hơn B và đảm bảo đúng chương được yêu cầu, với chi phí bằng 0 (dùng chung index). Đánh đổi: C phụ thuộc người dùng cung cấp đúng chương, chương sai sẽ loại mất chunk đúng; chunk theo đoạn dài hơn nên có lúc trộn nhiều ý (B vị trí 5) hoặc cắt bảng ở giới hạn 800 ký tự (vị trí 8). Phù hợp khi tài liệu có cấu trúc đoạn rõ và người dùng biết phạm vi chương; không suy rộng ra ngoài corpus này.
- Hạn chế:
    - Test chỉ có 5 câu và chỉ 1 câu filter; sai số rất lớn, không kết luận chiến lược tốt nhất nói chung.
    - Dev và test được chạy trong cùng một phiên trước khi chọn chiến lược, và benchmark chưa được commit trước khi chạy, nên kết quả test không hoàn toàn là holdout độc lập. Code và câu hỏi không bị sửa sau khi xem kết quả.
    - Cách gắn heading trong B được sửa một lần sau lần ingest đầu, dựa trên đọc mẫu chunk, không dựa trên điểm benchmark.
    - Chỉ có một tài liệu nên `document_id` không có tác dụng lọc; trường `section` của trang Summary (ví dụ trang 40 là 1.10) phản ánh trang chứ không phản ánh chủ đề của đoạn tóm tắt.
    - Thời gian đo một lần trên CPU, gồm cả overhead kết nối DB.
- Nếu làm lại: thử thư viện trích xuất khác (PyMuPDF) để giảm lỗi tách chữ; cho chunk B nối được qua ranh giới trang (ghi khoảng trang trong metadata); thêm overlap 1 câu cho B; thử hybrid BM25 + dense và model embedding lớn hơn; mở rộng test lên ≥ 15 câu với nhiều câu filter hơn; có người chấm thứ hai để đo độ đồng thuận.

