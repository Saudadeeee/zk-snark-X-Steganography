#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phân tích và tổng hợp thông tin download Verifier Package từ Wireshark CSV
Tính toán: tổng thời gian, tổng bytes, throughput, số file, v.v.
Tạo bảng tổng kết
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path
import re
from typing import Dict, List, Tuple, Optional
from collections import defaultdict
import json
import sys
import io

# Fix encoding for Windows console
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Setup matplotlib để hiển thị tiếng Việt
plt.rcParams['font.sans-serif'] = ['Arial', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

class SetupAnalyzer:
    """Phân tích dữ liệu download Verifier Package từ Wireshark CSV"""
    
    def __init__(self, csv_path: str):
        self.csv_path = csv_path
        self.df = None
        self.server_port = None
        self.download_sessions = []
        
    def load_data(self):
        """Đọc file CSV từ Wireshark"""
        print(f"Đang đọc file: {self.csv_path}")
        
        self.df = pd.read_csv(self.csv_path, quotechar='"')
        
        # Chuyển đổi kiểu dữ liệu
        self.df['No.'] = pd.to_numeric(self.df['No.'], errors='coerce')
        self.df['Time'] = pd.to_numeric(self.df['Time'], errors='coerce')
        self.df['Length'] = pd.to_numeric(self.df['Length'], errors='coerce')
        
        # Tự động phát hiện server port
        tcp_rows = self.df[self.df['Protocol'] == 'TCP']
        ports_found = []
        port_pattern = r'(\d{4,5})\s*>|>\s*(\d{4,5})'
        
        for info in tcp_rows['Info'].astype(str):
            matches = re.findall(port_pattern, info)
            for match in matches:
                port = match[0] if match[0] else match[1]
                if port and port not in ['443', '80', '8080', '53', '22']:
                    ports_found.append(port)
        
        if ports_found:
            from collections import Counter
            port_counts = Counter(ports_found)
            self.server_port = port_counts.most_common(1)[0][0]
            print(f"   Phát hiện server port: {self.server_port}")
        else:
            self.server_port = '8006'
            print(f"   Sử dụng port mặc định: {self.server_port}")
        
        print(f"   Tổng số packets: {len(self.df)}")
        
    def analyze_downloads(self):
        """Phân tích các HTTP download sessions"""
        print("\nĐang phân tích download sessions...")
        
        # Tìm tất cả HTTP GET requests đến verifier_package
        http_gets = self.df[
            (self.df['Protocol'] == 'HTTP') &
            (self.df['Info'].str.contains('GET /verifier_package', na=False))
        ].copy()
        
        print(f"   Tìm thấy {len(http_gets)} HTTP GET requests")
        
        # Phân tích từng download
        for idx, row in http_gets.iterrows():
            # Extract filename từ GET request
            info = str(row['Info'])
            match = re.search(r'GET /verifier_package/([^\s]+)', info)
            if not match:
                continue
            
            filename = match.group(1)
            start_time = row['Time']
            
            # Tìm server IP (Destination của GET request)
            server_ip = row['Destination']
            client_ip = row['Source']
            
            # Tìm TCP packets liên quan (từ server đến client, port 8006)
            # Tìm packets trong khoảng thời gian sau GET request
            end_idx = min(idx + 50, len(self.df))  # Tìm trong 50 packets tiếp theo
            related_packets = self.df[
                (self.df.index >= idx) &
                (self.df.index <= end_idx) &
                (self.df['Source'] == server_ip) &
                (self.df['Destination'] == client_ip) &
                (
                    (self.df['Protocol'] == 'TCP') |
                    (self.df['Protocol'] == 'HTTP')
                )
            ]
            
            # Tìm HTTP response
            http_response = related_packets[
                (related_packets['Protocol'] == 'HTTP') &
                (related_packets['Info'].str.contains('200 OK', na=False))
            ]
            
            if len(http_response) > 0:
                end_time = http_response.iloc[0]['Time']
                transfer_time = end_time - start_time
            else:
                # Nếu không tìm thấy HTTP response, dùng packet cuối cùng
                if len(related_packets) > 0:
                    end_time = related_packets.iloc[-1]['Time']
                    transfer_time = end_time - start_time
                else:
                    transfer_time = 0
                    end_time = start_time
            
            # Tính payload bytes (chỉ tính packets từ server)
            server_packets = related_packets[
                (related_packets['Source'] == server_ip) &
                (related_packets['Length'].notna())
            ]
            
            # Loại bỏ TCP headers (ước tính 66 bytes cho TCP/IP headers)
            payload_bytes = server_packets['Length'].sum() - (len(server_packets) * 66)
            payload_bytes = max(0, payload_bytes)  # Không được âm
            
            # Tính throughput (Mbps)
            if transfer_time > 0:
                throughput_mbps = (payload_bytes * 8) / (transfer_time * 1_000_000)
            else:
                throughput_mbps = 0
            
            # Đếm số packets
            total_packets = len(related_packets)
            server_packet_count = len(server_packets)
            
            # Tính average packet size
            if server_packet_count > 0:
                avg_packet_size = server_packets['Length'].mean()
            else:
                avg_packet_size = 0
            
            session_info = {
                'filename': filename,
                'start_time': start_time,
                'end_time': end_time,
                'transfer_time': transfer_time,
                'payload_bytes': int(payload_bytes),
                'throughput_mbps': throughput_mbps,
                'total_packets': total_packets,
                'server_packets': server_packet_count,
                'avg_packet_size': avg_packet_size,
                'file_size_bytes': int(payload_bytes)  # Ước tính từ payload
            }
            
            self.download_sessions.append(session_info)
        
        print(f"   Phân tích xong {len(self.download_sessions)} download sessions")
        
    def generate_summary(self) -> Dict:
        """Tạo bảng tổng kết"""
        if not self.download_sessions:
            return {}
        
        df_sessions = pd.DataFrame(self.download_sessions)
        
        summary = {
            'total_files': len(self.download_sessions),
            'total_time': df_sessions['transfer_time'].sum(),
            'total_bytes': df_sessions['payload_bytes'].sum(),
            'total_packets': df_sessions['total_packets'].sum(),
            'avg_transfer_time': df_sessions['transfer_time'].mean(),
            'avg_throughput_mbps': df_sessions['throughput_mbps'].mean(),
            'max_throughput_mbps': df_sessions['throughput_mbps'].max(),
            'min_throughput_mbps': df_sessions['throughput_mbps'].min(),
            'total_size_mb': df_sessions['payload_bytes'].sum() / (1024 * 1024),
            'avg_file_size_kb': df_sessions['payload_bytes'].mean() / 1024,
            'max_file_size_kb': df_sessions['payload_bytes'].max() / 1024,
            'min_file_size_kb': df_sessions['payload_bytes'].min() / 1024,
        }
        
        # Tính overall throughput
        if summary['total_time'] > 0:
            summary['overall_throughput_mbps'] = (summary['total_bytes'] * 8) / (summary['total_time'] * 1_000_000)
        else:
            summary['overall_throughput_mbps'] = 0
        
        return summary
    
    def print_summary_table(self, summary: Dict):
        """In bảng tổng kết"""
        print("\n" + "=" * 80)
        print("BẢNG TỔNG KẾT - DOWNLOAD VERIFIER PACKAGE")
        print("=" * 80)
        
        print(f"\n{'Thông số':<45} {'Giá trị':<35}")
        print("-" * 80)
        print(f"{'Tổng số file đã tải':<45} {summary['total_files']:<35}")
        print(f"{'Tổng thời gian download':<45} {summary['total_time']:.3f} giây")
        print(f"{'Tổng dung lượng':<45} {summary['total_size_mb']:.3f} MB ({summary['total_bytes']:,} bytes)")
        print(f"{'Tổng số packets':<45} {summary['total_packets']:<35}")
        print(f"{'Thời gian trung bình/file':<45} {summary['avg_transfer_time']:.3f} giây")
        print(f"{'Dung lượng trung bình/file':<45} {summary['avg_file_size_kb']:.2f} KB")
        print(f"{'Dung lượng lớn nhất':<45} {summary['max_file_size_kb']:.2f} KB")
        print(f"{'Dung lượng nhỏ nhất':<45} {summary['min_file_size_kb']:.2f} KB")
        print(f"{'Throughput trung bình':<45} {summary['avg_throughput_mbps']:.3f} Mbps")
        print(f"{'Throughput tối đa':<45} {summary['max_throughput_mbps']:.3f} Mbps")
        print(f"{'Throughput tối thiểu':<45} {summary['min_throughput_mbps']:.3f} Mbps")
        print(f"{'Throughput tổng thể':<45} {summary['overall_throughput_mbps']:.3f} Mbps")
        
        print("\n" + "=" * 80)
        print("CHI TIẾT TỪNG FILE")
        print("=" * 80)
        
        df_sessions = pd.DataFrame(self.download_sessions)
        df_sessions = df_sessions.sort_values('start_time')
        
        print(f"\n{'STT':<5} {'Tên file':<50} {'Kích thước (KB)':<20} {'Thời gian (s)':<20} {'Throughput (Mbps)':<20}")
        print("-" * 115)
        
        for idx, row in df_sessions.iterrows():
            print(f"{idx+1:<5} {row['filename']:<50} {row['payload_bytes']/1024:>18.2f} {row['transfer_time']:>18.3f} {row['throughput_mbps']:>18.3f}")
        
        print("=" * 80)
    
    def save_results(self, summary: Dict, output_dir: str = "Setup_Result"):
        """Lưu kết quả vào file JSON và CSV"""
        output_path = Path(output_dir)
        output_path.mkdir(exist_ok=True)
        
        # Convert numpy types to Python native types for JSON
        summary_serializable = {}
        for key, value in summary.items():
            if isinstance(value, (np.integer, np.int64)):
                summary_serializable[key] = int(value)
            elif isinstance(value, (np.floating, np.float64)):
                summary_serializable[key] = float(value)
            else:
                summary_serializable[key] = value
        
        # Lưu summary JSON
        summary_file = output_path / "setup_summary.json"
        with open(summary_file, 'w', encoding='utf-8') as f:
            json.dump(summary_serializable, f, indent=2, ensure_ascii=False)
        print(f"\nĐã lưu summary: {summary_file}")
        
        # Lưu chi tiết CSV
        df_sessions = pd.DataFrame(self.download_sessions)
        detail_file = output_path / "setup_details.csv"
        df_sessions.to_csv(detail_file, index=False, encoding='utf-8-sig')
        print(f"Đã lưu chi tiết: {detail_file}")
        
        return output_path

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Phân tích download Verifier Package từ Wireshark CSV')
    parser.add_argument('csv_file', nargs='?', default='wifi_benchmark/Setup.csv',
                       help='Đường dẫn đến file CSV từ Wireshark (default: wifi_benchmark/Setup.csv)')
    parser.add_argument('-o', '--output', default='Setup_Result',
                       help='Thư mục output (default: Setup_Result)')
    
    args = parser.parse_args()
    
    # Kiểm tra file tồn tại
    csv_path = Path(args.csv_file)
    if not csv_path.exists():
        print(f"ERROR: File không tồn tại: {csv_path}")
        sys.exit(1)
    
    # Phân tích
    analyzer = SetupAnalyzer(str(csv_path))
    analyzer.load_data()
    analyzer.analyze_downloads()
    
    # Tạo summary
    summary = analyzer.generate_summary()
    
    if not summary:
        print("ERROR: Không tìm thấy dữ liệu download")
        sys.exit(1)
    
    # In bảng tổng kết
    analyzer.print_summary_table(summary)
    
    # Lưu kết quả
    output_path = analyzer.save_results(summary, args.output)
    
    print(f"\n✓ Hoàn thành! Kết quả đã được lưu tại: {output_path.absolute()}")

if __name__ == "__main__":
    main()

