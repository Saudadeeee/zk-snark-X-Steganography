#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phân tích và tổng hợp thông tin download stego_benchmark.png từ Pairing.csv
Tạo bảng tổng kết tương tự như Setup.csv
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path
import re
from typing import Dict, List, Tuple, Optional
from collections import defaultdict, Counter
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

class StegoPairingAnalyzer:
    """Phân tích download stego_benchmark.png từ Pairing.csv"""
    
    def __init__(self, csv_path: str):
        self.csv_path = csv_path
        self.df = None
        self.server_port = None
        self.stego_sessions = []
        
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
            port_counts = Counter(ports_found)
            self.server_port = port_counts.most_common(1)[0][0]
            print(f"   Phát hiện server port: {self.server_port}")
        else:
            self.server_port = '8000'
            print(f"   Sử dụng port mặc định: {self.server_port}")
        
        print(f"   Tổng số packets: {len(self.df)}")
        
    def extract_stego_sessions(self):
        """Tách các session download stego_benchmark.png"""
        print("\nĐang tìm các session download stego_benchmark.png...")
        
        # Tìm tất cả HTTP GET requests đến stego_benchmark.png
        stego_gets = self.df[
            (self.df['Protocol'] == 'HTTP') &
            (self.df['Info'].str.contains('GET /stego_benchmark.png', na=False))
        ].copy()
        
        print(f"   Tìm thấy {len(stego_gets)} HTTP GET requests cho stego_benchmark.png")
        
        # Phân tích từng session
        for idx, row in stego_gets.iterrows():
            start_time = row['Time']
            server_ip = row['Destination']
            client_ip = row['Source']
            
            # Tìm packets liên quan trong khoảng thời gian hợp lý
            # Tìm đến khi có HTTP response hoặc TCP FIN
            end_idx = min(idx + 200, len(self.df))  # Tìm trong 200 packets tiếp theo
            related_packets = self.df[
                (self.df.index >= idx) &
                (self.df.index <= end_idx) &
                (
                    (self.df['Source'] == server_ip) & (self.df['Destination'] == client_ip) |
                    (self.df['Source'] == client_ip) & (self.df['Destination'] == server_ip)
                ) &
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
                # Nếu không tìm thấy HTTP response, tìm TCP FIN hoặc packet cuối cùng
                fin_packets = related_packets[
                    related_packets['Info'].str.contains('FIN', na=False)
                ]
                if len(fin_packets) > 0:
                    end_time = fin_packets.iloc[-1]['Time']
                    transfer_time = end_time - start_time
                elif len(related_packets) > 0:
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
            # Chỉ tính packets có data (PSH hoặc HTTP)
            data_packets = server_packets[
                server_packets['Info'].str.contains('PSH|HTTP', na=False, regex=True)
            ]
            
            payload_bytes = data_packets['Length'].sum() - (len(data_packets) * 66)
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
            
            # Tính latency (từ GET đến response đầu tiên)
            latency = 0
            if len(http_response) > 0:
                latency = (http_response.iloc[0]['Time'] - start_time) * 1000  # ms
            
            session_info = {
                'session_id': len(self.stego_sessions) + 1,
                'start_time': start_time,
                'end_time': end_time,
                'transfer_time': transfer_time,
                'payload_bytes': int(payload_bytes),
                'throughput_mbps': throughput_mbps,
                'total_packets': total_packets,
                'server_packets': server_packet_count,
                'avg_packet_size': avg_packet_size,
                'latency_ms': latency,
                'file_size_bytes': int(payload_bytes)
            }
            
            self.stego_sessions.append(session_info)
        
        print(f"   Phân tích xong {len(self.stego_sessions)} download sessions")
        
    def generate_summary(self) -> Dict:
        """Tạo bảng tổng kết cho 1 lần tải đầu tiên"""
        if not self.stego_sessions:
            return {}
        
        # Chỉ lấy session đầu tiên
        first_session = self.stego_sessions[0]
        
        summary = {
            'session_id': first_session['session_id'],
            'transfer_time': first_session['transfer_time'],
            'payload_bytes': first_session['payload_bytes'],
            'total_packets': first_session['total_packets'],
            'server_packets': first_session['server_packets'],
            'throughput_mbps': first_session['throughput_mbps'],
            'file_size_kb': first_session['payload_bytes'] / 1024,
            'file_size_mb': first_session['payload_bytes'] / (1024 * 1024),
            'latency_ms': first_session['latency_ms'],
            'avg_packet_size': first_session['avg_packet_size'],
        }
        
        return summary
    
    def print_summary_table(self, summary: Dict):
        """In bảng tổng kết cho 1 lần tải"""
        print("\n" + "=" * 80)
        print("BẢNG TỔNG KẾT - DOWNLOAD STEGO_BENCHMARK.PNG (1 LẦN TẢI)")
        print("=" * 80)
        
        print(f"\n{'Thông số':<45} {'Giá trị':<35}")
        print("-" * 80)
        print(f"{'Tên file':<45} {'stego_benchmark.png':<35}")
        print(f"{'Thời gian download':<45} {summary['transfer_time']:.3f} giây")
        print(f"{'Dung lượng':<45} {summary['file_size_mb']:.3f} MB ({summary['payload_bytes']:,} bytes)")
        print(f"{'Dung lượng (KB)':<45} {summary['file_size_kb']:.2f} KB")
        print(f"{'Tổng số packets':<45} {summary['total_packets']:<35}")
        print(f"{'Số packets từ server':<45} {summary['server_packets']:<35}")
        print(f"{'Kích thước packet trung bình':<45} {summary['avg_packet_size']:.2f} bytes")
        print(f"{'Latency':<45} {summary['latency_ms']:.2f} ms")
        print(f"{'Throughput':<45} {summary['throughput_mbps']:.3f} Mbps")
        print("=" * 80)
    
    def save_results(self, summary: Dict, output_dir: str = "Stego_Pairing_Result"):
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
        summary_file = output_path / "stego_summary.json"
        with open(summary_file, 'w', encoding='utf-8') as f:
            json.dump(summary_serializable, f, indent=2, ensure_ascii=False)
        print(f"\nĐã lưu summary: {summary_file}")
        
        # Lưu chi tiết CSV (chỉ session đầu tiên)
        first_session = self.stego_sessions[0] if self.stego_sessions else {}
        df_session = pd.DataFrame([first_session])
        detail_file = output_path / "stego_details.csv"
        df_session.to_csv(detail_file, index=False, encoding='utf-8-sig')
        print(f"Đã lưu chi tiết: {detail_file}")
        
        return output_path

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Phân tích download stego_benchmark.png từ Pairing.csv')
    parser.add_argument('csv_file', nargs='?', default='wifi_benchmark/Pairing.csv',
                       help='Đường dẫn đến file Pairing.csv (default: wifi_benchmark/Pairing.csv)')
    parser.add_argument('-o', '--output', default='Stego_Pairing_Result',
                       help='Thư mục output (default: Stego_Pairing_Result)')
    
    args = parser.parse_args()
    
    # Kiểm tra file tồn tại
    csv_path = Path(args.csv_file)
    if not csv_path.exists():
        print(f"ERROR: File không tồn tại: {csv_path}")
        sys.exit(1)
    
    # Phân tích
    analyzer = StegoPairingAnalyzer(str(csv_path))
    analyzer.load_data()
    analyzer.extract_stego_sessions()
    
    # Tạo summary
    summary = analyzer.generate_summary()
    
    if not summary:
        print("ERROR: Không tìm thấy dữ liệu download stego_benchmark.png")
        sys.exit(1)
    
    # In bảng tổng kết
    analyzer.print_summary_table(summary)
    
    # Lưu kết quả
    output_path = analyzer.save_results(summary, args.output)
    
    print(f"\n✓ Hoàn thành! Kết quả đã được lưu tại: {output_path.absolute()}")

if __name__ == "__main__":
    main()

