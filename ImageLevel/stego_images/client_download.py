"""
Script để tải ảnh từ server (chạy trên máy B - Client)
Đảm bảo tải file nguyên vẹn, không mất bit
"""
import urllib.request
import sys
import os
from pathlib import Path

def download_file(server_url, filename, output_dir="downloaded_images"):
    """
    Tải file từ server và lưu vào thư mục output_dir
    
    Args:
        server_url: URL của server (ví dụ: http://192.168.1.100:8000)
        filename: Tên file cần tải (ví dụ: stego_benchmark.png)
        output_dir: Thư mục lưu file (mặc định: downloaded_images)
    """
    # Tạo thư mục output nếu chưa có
    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)
    
    # URL đầy đủ
    file_url = f"{server_url.rstrip('/')}/{filename}"
    output_file = output_path / filename
    
    print(f"Đang tải: {file_url}")
    print(f"Lưu vào: {output_file}")
    
    try:
        # Tải file với binary mode để giữ nguyên tất cả các bit
        urllib.request.urlretrieve(file_url, output_file)
        
        # Kiểm tra file đã tải
        if output_file.exists():
            file_size = output_file.stat().st_size
            print(f"✓ Tải thành công: {filename} ({file_size:,} bytes)")
            return True
        else:
            print(f"✗ Lỗi: File không được tạo")
            return False
            
    except urllib.error.HTTPError as e:
        print(f"✗ Lỗi HTTP {e.code}: {e.reason}")
        return False
    except urllib.error.URLError as e:
        print(f"✗ Lỗi kết nối: {e.reason}")
        print(f"  Kiểm tra lại:")
        print(f"  - Server có đang chạy không?")
        print(f"  - IP address có đúng không?")
        print(f"  - Firewall có chặn port 8000 không?")
        return False
    except Exception as e:
        print(f"✗ Lỗi không xác định: {e}")
        return False


def verify_file_integrity(file1_path, file2_path):
    """
    So sánh 2 file để đảm bảo chúng giống hệt nhau (bit-by-bit)
    
    Args:
        file1_path: Đường dẫn file 1
        file2_path: Đường dẫn file 2
    
    Returns:
        True nếu 2 file giống hệt nhau, False nếu khác
    """
    file1 = Path(file1_path)
    file2 = Path(file2_path)
    
    if not file1.exists() or not file2.exists():
        print("✗ Một trong hai file không tồn tại")
        return False
    
    size1 = file1.stat().st_size
    size2 = file2.stat().st_size
    
    if size1 != size2:
        print(f"✗ Kích thước khác nhau: {size1} vs {size2} bytes")
        return False
    
    print(f"Đang so sánh {size1:,} bytes...")
    
    # So sánh từng byte
    with open(file1, "rb") as f1, open(file2, "rb") as f2:
        chunk_size = 8192
        bytes_read = 0
        while True:
            chunk1 = f1.read(chunk_size)
            chunk2 = f2.read(chunk_size)
            
            if chunk1 != chunk2:
                print(f"✗ File khác nhau tại byte {bytes_read}")
                return False
            
            if not chunk1:
                break
            
            bytes_read += len(chunk1)
    
    print("✓ Hai file giống hệt nhau (bit-by-bit)")
    return True


def main():
    """Main function"""
    if len(sys.argv) < 3:
        print("Cách sử dụng:")
        print(f"  python {sys.argv[0]} <server_url> <filename> [output_dir]")
        print("")
        print("Ví dụ:")
        print(f"  python {sys.argv[0]} http://192.168.1.100:8000 stego_benchmark.png")
        print(f"  python {sys.argv[0]} http://192.168.1.100:8000 original_image.webp downloaded_images")
        print("")
        print("Các file có sẵn trên server:")
        print("  - stego_benchmark.png")
        print("  - original_benchmark.png")
        print("  - original_image.webp")
        sys.exit(1)
    
    server_url = sys.argv[1]
    filename = sys.argv[2]
    output_dir = sys.argv[3] if len(sys.argv) > 3 else "downloaded_images"
    
    # Tải file
    success = download_file(server_url, filename, output_dir)
    
    if success:
        print(f"\n✓ Hoàn thành! File đã được lưu vào: {output_dir}/{filename}")
        print("\nLưu ý: File đã được tải ở chế độ binary để giữ nguyên tất cả các bit.")
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
