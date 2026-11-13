# Bài làm — Nguyễn Đăng Doanh (2A202603597)

Pipeline ingest *Principles of Finance* (OpenStax, ch.1–3) vào PostgreSQL + pgvector và so sánh 3 chiến lược A/B/C. Báo cáo: [report/individual/2A202603597_NguyenDangDoanh.md](report/individual/2A202603597_NguyenDangDoanh.md).

## Setup 

```powershell
cd starter
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt sentence-transformers==6.3.0
Copy-Item .env.example .env
docker compose -p day6_student_starter up -d --wait
python scripts/check_setup.py
```

Model embedding `sentence-transformers/all-MiniLM-L6-v2` tự tải về ở lần chạy đầu; không cần API key.

## Chạy

```powershell
python scripts/inventory_pages.py data/100pages.pdf   
python scripts/validate_benchmark.py                  
python -m src.run ingest                             
python -m src.run check-reingest                      
python -m src.run evaluate --split dev                
python -m src.run evaluate --split test              
python -m src.run export-audit                      
python -m src.run summarize-audit                   
```

## Cấu trúc

| Đường dẫn | Nội dung |
|---|---|
| `data/manifest.csv`, `data/page_inventory.csv` | Nguồn, giấy phép, quy tắc đếm trang, phân loại từng trang |
| `starter/data/100pages.pdf` | Corpus (CC BY 4.0) |
| `benchmark/` | 20 câu hỏi (15 dev / 5 test), gold evidence, cách chia, tiêu chí chọn |
| `starter/src/` | Code pipeline (`config`, `ingestion`, `chunking`, `embeddings`, `store`, `evaluation`, `experiments`, `run`) |
| `starter/scripts/` | Kiểm kê trang, in text đã chuẩn hóa, kiểm chứng benchmark |
| `artifacts/experiment_log.csv` | Tham số, giả thuyết và kết quả A/B/C |
| `starter/results/` | Thống kê ingest, log, kiểm tra nạp lại, trace, chỉ số, nhãn chấm |

---



# Day 06 · Data Ingestion Engineering

**Lab cá nhân** · **4 giờ** · **Dữ liệu tự chọn**

Biến tài liệu thành kho tri thức có thể truy xuất cho AI agent, rồi đo xem cách chuẩn bị dữ liệu nào hiệu quả nhất.

| 📄 Dữ liệu | 🧩 Chiến lược | 🎯 Benchmark |
|---|---|---|
| Tối thiểu **30 trang nội dung** | Tối thiểu **3 cấu hình** | Tối thiểu **20 câu hỏi** |

## Bắt đầu nhanh

Dùng [starter PostgreSQL + pgvector](starter/README.md) để dựng database và hoàn thiện các hàm TODO, hoặc tự chọn vector store tương đương. Starter chỉ là khung: **bạn tự hiện thực pipeline và benchmark**.

## 1. Xây pipeline

![Đọc tài liệu, chuẩn hóa, chia chunk, tạo vector, lưu và kiểm tra](assets/ingestion-pipeline.svg)

Chọn tài liệu được phép sử dụng; giữ **ID tài liệu, nguồn, trang/vị trí** và metadata phù hợp. Dùng embedding model thật qua API hoặc chạy local; lưu và truy xuất bằng pgvector, Qdrant, Chroma hoặc một store tương đương.

## 2. So sánh và đánh giá

![Ba chiến lược được đánh giá trên cùng corpus và benchmark dev/test](assets/benchmark-workflow.svg)

Dùng cùng dữ liệu, model và câu hỏi cho cả ba cấu hình. Tách **15 câu dev / 5 câu test** trước khi chạy; chọn cấu hình trên dev, rồi đánh giá test sau khi cố định. Mỗi câu hỏi cần có đoạn bằng chứng và trang nguồn; thiết kế bộ câu hỏi và đánh giá theo [BENCHMARK.md](BENCHMARK.md).

Đánh giá theo năm khía cạnh: **độ chính xác truy xuất**, **tính mạch lạc của chunk**, **tính hữu dụng của metadata**, **chất lượng grounding** và **tác động của chiến lược dữ liệu**. Giải thích lựa chọn bằng kết quả, ví dụ lỗi và các đánh đổi.

## 3. Chuẩn bị bài nộp

1. Chạy pipeline và lưu cấu hình, kết quả top-3, trace cùng nhãn đánh giá thủ công.
2. Điền [thông tin học viên](STUDENT.md), [nhật ký thí nghiệm](artifacts/experiment_log.csv) và bản sao [mẫu báo cáo cá nhân](report/individual/MSSV_HoTen.md).
3. Kiểm tra mã nguồn, cách chạy, manifest dữ liệu và checklist trong [SUBMISSION.md](SUBMISSION.md).

## Tài liệu hướng dẫn

| Bạn cần tìm | Tài liệu |
|---|---|
| Setup baseline PostgreSQL + pgvector | [starter/README.md](starter/README.md) |
| Các bước làm và cách tính chỉ số | [GUIDE.md](GUIDE.md) |
| Tiến độ trong 4 giờ | [CHECKPOINTS.md](CHECKPOINTS.md) |
| Năm tiêu chí benchmark và bộ câu hỏi | [BENCHMARK.md](BENCHMARK.md) |
| Tiêu chí chấm điểm | [RUBRIC.md](RUBRIC.md) |
| Quy tắc sử dụng dữ liệu, AI và API | [RULES.md](RULES.md) |
| Cách nộp bài | [SUBMISSION.md](SUBMISSION.md) |

[data/format-example.json](data/format-example.json) chỉ minh họa định dạng, không phải corpus đủ điều kiện. Phần xử lý và benchmark do bạn tự hiện thực; không bắt buộc xây chatbot.
