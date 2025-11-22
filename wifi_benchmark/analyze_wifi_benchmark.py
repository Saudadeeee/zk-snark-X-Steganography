"""
Phân tích và so sánh dữ liệu Wireshark cho ảnh Origin và Stego
Tính toán các metrics: throughput, packet loss, payload size, latency, etc.
Vẽ biểu đồ và bảng so sánh
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

class WiresharkAnalyzer:
    """Phân tích dữ liệu từ Wireshark CSV"""
    
    def __init__(self, csv_path: str):
        self.csv_path = csv_path
        self.df = None
        self.sessions = []
        self.server_port = None  # Port của server (sẽ được phát hiện tự động)
        
    def load_data(self):
        """Đọc file CSV từ Wireshark"""
        print(f"Đang đọc file: {self.csv_path}")
        
        # Đọc CSV với các cột: No., Time, Source, Destination, Protocol, Length, Info
        self.df = pd.read_csv(self.csv_path, quotechar='"')
        
        # Chuyển đổi kiểu dữ liệu
        self.df['No.'] = pd.to_numeric(self.df['No.'], errors='coerce')
        self.df['Time'] = pd.to_numeric(self.df['Time'], errors='coerce')
        self.df['Length'] = pd.to_numeric(self.df['Length'], errors='coerce')
        
        # Tự động phát hiện server port từ TCP packets
        # Port server thường xuất hiện trong format: "8004  >" hoặc ">  8004"
        tcp_rows = self.df[self.df['Protocol'] == 'TCP']
        ports_found = []
        
        # Pattern để tìm port: số 4-5 chữ số kèm theo dấu > hoặc <
        port_pattern = r'(\d{4,5})\s*>|>\s*(\d{4,5})'
        
        for info in tcp_rows['Info'].astype(str):
            matches = re.findall(port_pattern, info)
            for match in matches:
                port = match[0] if match[0] else match[1]
                if port and port not in ['443', '80', '8080', '53', '22']:  # Loại bỏ các port phổ biến khác
                    ports_found.append(port)
        
        if ports_found:
            # Lấy port xuất hiện nhiều nhất (thường là server port)
            port_counts = Counter(ports_found)
            self.server_port = port_counts.most_common(1)[0][0]
            print(f"   Phát hiện server port: {self.server_port}")
        else:
            # Fallback: tìm port trong các TCP packets gần HTTP GET
            http_get_indices = self.df[
                (self.df['Protocol'] == 'HTTP') & 
                (self.df['Info'].str.contains('GET', na=False))
            ].index
            
            if len(http_get_indices) > 0:
                # Tìm TCP packets gần HTTP GET requests
                for idx in http_get_indices[:5]:  # Chỉ kiểm tra 5 GET đầu tiên
                    nearby_tcp = self.df[
                        (self.df['Protocol'] == 'TCP') &
                        (self.df.index >= max(0, idx - 5)) &
                        (self.df.index <= idx + 5)
                    ]
                    for info in nearby_tcp['Info'].astype(str):
                        # Tìm pattern "port >" hoặc "> port"
                        match = re.search(r'(\d{4,5})\s*>|>\s*(\d{4,5})', info)
                        if match:
                            port = match.group(1) if match.group(1) else match.group(2)
                            if port and port not in ['443', '80', '8080', '53', '22']:
                                self.server_port = port
                                print(f"   Phát hiện server port: {self.server_port}")
                                break
                    if self.server_port:
                        break
        
        # Nếu không tìm thấy, dùng port mặc định 8000
        if self.server_port is None:
            self.server_port = '8000'
            print(f"   Sử dụng port mặc định: {self.server_port}")
        
        # Lọc các packet liên quan đến HTTP/TCP trên port đã phát hiện
        mask = (
            (self.df['Protocol'].isin(['HTTP', 'TCP'])) &
            (
                self.df['Info'].str.contains(self.server_port, na=False) | 
                self.df['Info'].str.contains('GET', na=False) |
                self.df['Info'].str.contains('HTTP', na=False, case=False)
            )
        )
        self.df = self.df[mask].copy()
        
        # Sắp xếp theo thời gian
        self.df = self.df.sort_values('Time').reset_index(drop=True)
        
        print(f"Đã đọc {len(self.df)} packets")
        return self.df
    
    def extract_sessions(self):
        """Tách các session (mỗi lần tải file) từ dữ liệu"""
        sessions = []
        current_session = None
        last_get_time = None
        
        for idx, row in self.df.iterrows():
            info = str(row['Info']).upper()
            protocol = str(row['Protocol']).upper()
            
            # Tìm HTTP GET request - bắt đầu session mới
            if 'GET' in info and 'HTTP' in protocol:
                # Lưu session cũ nếu có
                if current_session is not None and len(current_session['packets']) > 0:
                    sessions.append(current_session)
                
                # Kiểm tra nếu có khoảng cách thời gian lớn (> 1s) từ GET trước
                # thì đây là session mới
                current_time = row['Time']
                if last_get_time is not None and current_time - last_get_time > 1.0:
                    # Session mới rõ ràng
                    pass
                
                last_get_time = current_time
                
                # Xác định loại ảnh từ URL
                http_info = str(row['Info'])
                image_type = None
                # Kiểm tra chính xác tên file trong URL
                if 'original_benchmark.png' in http_info:
                    image_type = 'origin'
                elif 'stego_benchmark.png' in http_info:
                    image_type = 'stego'
                # Fallback: kiểm tra từ khóa trong URL
                elif 'original' in http_info.lower() and 'stego' not in http_info.lower():
                    image_type = 'origin'
                elif 'stego' in http_info.lower():
                    image_type = 'stego'
                
                # Tạo session mới
                current_session = {
                    'session_id': len(sessions) + 1,
                    'start_time': row['Time'],
                    'start_packet': row['No.'],
                    'packets': [],
                    'http_request': row['Info'],
                    'image_type': image_type  # 'origin' hoặc 'stego'
                }
            
            # Thêm packet vào session hiện tại
            if current_session is not None:
                current_session['packets'].append({
                    'no': row['No.'],
                    'time': row['Time'],
                    'source': row['Source'],
                    'dest': row['Destination'],
                    'protocol': row['Protocol'],
                    'length': row['Length'],
                    'info': row['Info']
                })
                
                # Cập nhật thời gian kết thúc
                current_session['end_time'] = row['Time']
                current_session['end_packet'] = row['No.']
        
        # Thêm session cuối cùng
        if current_session is not None and len(current_session['packets']) > 0:
            sessions.append(current_session)
        
        self.sessions = sessions
        print(f"Đã tìm thấy {len(sessions)} sessions")
        return sessions
    
    def split_sessions_by_type(self):
        """Tách sessions thành origin và stego"""
        origin_sessions = [s for s in self.sessions if s.get('image_type') == 'origin']
        stego_sessions = [s for s in self.sessions if s.get('image_type') == 'stego']
        unclassified = [s for s in self.sessions if s.get('image_type') is None]
        
        if unclassified:
            print(f"   Cảnh báo: Có {len(unclassified)} sessions không được phân loại (không tìm thấy origin/stego trong URL)")
            for session in unclassified[:5]:  # Hiển thị 5 session đầu tiên
                print(f"      - Session {session.get('session_id')}: {session.get('http_request', 'N/A')[:80]}")
        
        # Đánh lại số session_id cho mỗi loại
        for i, session in enumerate(origin_sessions, 1):
            session['session_id'] = i
        for i, session in enumerate(stego_sessions, 1):
            session['session_id'] = i
        
        return origin_sessions, stego_sessions
    
    def analyze_session(self, session: Dict) -> Dict:
        """Phân tích một session và tính toán các metrics"""
        packets = session['packets']
        
        if not packets:
            return None
        
        # Tính toán thời gian transfer
        transfer_time = session['end_time'] - session['start_time']
        
        # Phân loại packets
        tcp_packets = [p for p in packets if p['protocol'] == 'TCP']
        http_packets = [p for p in packets if p['protocol'] == 'HTTP']
        
        # Packets từ server (sử dụng port đã phát hiện)
        server_port = self.server_port or '8000'
        server_packets = [
            p for p in packets 
            if f':{server_port}' in str(p['info']) or 
               f'{server_port}  >' in str(p['info']) or
               f'{server_port} >' in str(p['info'])
        ]
        client_packets = [
            p for p in packets 
            if f'>  {server_port}' in str(p['info']) or
               f'> {server_port}' in str(p['info'])
        ]
        
        # Tính tổng bytes
        total_bytes = sum(p['length'] for p in packets)
        server_bytes = sum(p['length'] for p in server_packets)
        client_bytes = sum(p['length'] for p in client_packets)
        
        # Payload bytes (chỉ tính data packets, không tính ACK)
        payload_packets = [
            p for p in server_packets 
            if 'PSH' in str(p['info']) or 'HTTP' in str(p['protocol'])
        ]
        payload_bytes = sum(p['length'] for p in payload_packets)
        
        # Packet sizes
        packet_sizes = [p['length'] for p in packets]
        payload_sizes = [p['length'] for p in payload_packets]
        
        # Tính packet loss (dựa vào TCP retransmissions và out-of-order)
        retransmissions = sum(1 for p in packets if 'retransmission' in str(p['info']).lower())
        out_of_order = sum(1 for p in packets if 'out-of-order' in str(p['info']).lower())
        duplicates = sum(1 for p in packets if 'duplicate' in str(p['info']).lower())
        total_loss_indicators = retransmissions + out_of_order + duplicates
        
        # Tính throughput (Mbps)
        if transfer_time > 0:
            throughput_mbps = (payload_bytes * 8) / (transfer_time * 1_000_000)
            throughput_mbps_total = (total_bytes * 8) / (transfer_time * 1_000_000)
        else:
            throughput_mbps = 0
            throughput_mbps_total = 0
        
        # Tính latency (RTT - Round Trip Time)
        # Tìm các cặp request-response từ HTTP GET đến response đầu tiên
        latencies = []
        http_get_packets = [p for p in packets if 'GET' in str(p['info']) and 'HTTP' in str(p['protocol'])]
        
        for get_pkt in http_get_packets[:1]:  # Chỉ lấy GET request đầu tiên
            # Tìm response đầu tiên sau GET request
            for resp_pkt in server_packets:
                if resp_pkt['time'] > get_pkt['time'] and resp_pkt['time'] - get_pkt['time'] < 1.0:
                    # Tìm ACK từ client cho response này
                    for ack_pkt in client_packets:
                        if ack_pkt['time'] > resp_pkt['time'] and ack_pkt['time'] - resp_pkt['time'] < 0.1:
                            rtt = (ack_pkt['time'] - get_pkt['time']) * 1000  # ms
                            latencies.append(rtt)
                            break
                    break
        
        # Nếu không tìm được RTT, tính latency đơn giản từ GET đến response đầu tiên
        if not latencies and http_get_packets and server_packets:
            get_time = http_get_packets[0]['time']
            first_resp = next((p for p in server_packets if p['time'] > get_time), None)
            if first_resp:
                latencies.append((first_resp['time'] - get_time) * 1000)
        
        avg_latency = np.mean(latencies) if latencies else 0
        
        # Tính packets per second
        pps = len(packets) / transfer_time if transfer_time > 0 else 0
        
        return {
            'session_id': session['session_id'],
            'transfer_time': transfer_time,
            'total_packets': len(packets),
            'tcp_packets': len(tcp_packets),
            'http_packets': len(http_packets),
            'total_bytes': total_bytes,
            'server_bytes': server_bytes,
            'client_bytes': client_bytes,
            'payload_bytes': payload_bytes,
            'avg_packet_size': np.mean(packet_sizes) if packet_sizes else 0,
            'max_packet_size': max(packet_sizes) if packet_sizes else 0,
            'min_packet_size': min(packet_sizes) if packet_sizes else 0,
            'avg_payload_size': np.mean(payload_sizes) if payload_sizes else 0,
            'max_payload_size': max(payload_sizes) if payload_sizes else 0,
            'min_payload_size': min(payload_sizes) if payload_sizes else 0,
            'retransmissions': retransmissions,
            'out_of_order': out_of_order,
            'duplicates': duplicates,
            'packet_loss_indicators': total_loss_indicators,
            'packet_loss_rate': (total_loss_indicators / len(packets) * 100) if packets else 0,
            'throughput_mbps': throughput_mbps,
            'throughput_mbps_total': throughput_mbps_total,
            'avg_latency_ms': avg_latency,
            'packets_per_second': pps,
            'start_time': session['start_time'],
            'end_time': session['end_time']
        }
    
    def analyze_all_sessions(self) -> List[Dict]:
        """Phân tích tất cả sessions"""
        results = []
        for session in self.sessions:
            result = self.analyze_session(session)
            if result:
                results.append(result)
        return results


class BenchmarkComparator:
    """So sánh kết quả giữa Origin và Stego"""
    
    def __init__(self, origin_results: List[Dict], stego_results: List[Dict]):
        self.origin_results = origin_results
        self.stego_results = stego_results
        self.origin_df = pd.DataFrame(origin_results)
        self.stego_df = pd.DataFrame(stego_results)
    
    def calculate_statistics(self, df: pd.DataFrame) -> Dict:
        """Tính toán thống kê từ DataFrame"""
        stats = {}
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        
        for col in numeric_cols:
            stats[f'{col}_mean'] = df[col].mean()
            stats[f'{col}_std'] = df[col].std()
            stats[f'{col}_min'] = df[col].min()
            stats[f'{col}_max'] = df[col].max()
            stats[f'{col}_median'] = df[col].median()
        
        return stats
    
    def create_comparison_table(self) -> pd.DataFrame:
        """Tạo bảng so sánh giữa Origin và Stego"""
        metrics = [
            'transfer_time', 'total_packets', 'total_bytes', 'payload_bytes',
            'throughput_mbps', 'avg_packet_size', 'avg_payload_size',
            'packet_loss_rate', 'avg_latency_ms', 'packets_per_second'
        ]
        
        comparison_data = []
        
        for metric in metrics:
            orig_mean = self.origin_df[metric].mean()
            orig_std = self.origin_df[metric].std()
            stego_mean = self.stego_df[metric].mean()
            stego_std = self.stego_df[metric].std()
            
            diff = stego_mean - orig_mean
            diff_pct = (diff / orig_mean * 100) if orig_mean != 0 else 0
            
            comparison_data.append({
                'Metric': metric.replace('_', ' ').title(),
                'Origin (Mean)': f"{orig_mean:.4f}",
                'Origin (Std)': f"±{orig_std:.4f}",
                'Stego (Mean)': f"{stego_mean:.4f}",
                'Stego (Std)': f"±{stego_std:.4f}",
                'Difference': f"{diff:.4f}",
                'Difference (%)': f"{diff_pct:.2f}%"
            })
        
        return pd.DataFrame(comparison_data)
    
    def plot_comparison(self, output_dir: Path):
        """Vẽ các biểu đồ so sánh - Tất cả đều là biểu đồ đường với ký hiệu rõ ràng"""
        output_dir.mkdir(exist_ok=True, parents=True)
        
        # Cấu hình markers lớn và rõ ràng
        marker_size = 10
        line_width = 2.5
        marker_style_origin = 'o'  # Circle
        marker_style_stego = 's'  # Square
        color_origin = '#2ecc71'  # Green
        color_stego = '#e74c3c'   # Red
        
        # 1. Biểu đồ đường so sánh các metrics chính (theo session giống performance_trends)
        fig, axes = plt.subplots(2, 3, figsize=(18, 12))
        fig.suptitle('So sánh Origin vs Stego - Các Metrics Chính', fontsize=16, fontweight='bold')
        
        metrics_to_plot = [
            ('throughput_mbps', 'Throughput (Mbps)', axes[0, 0]),
            ('transfer_time', 'Transfer Time (s)', axes[0, 1]),
            ('total_packets', 'Total Packets', axes[0, 2]),
            ('payload_bytes', 'Payload Size (bytes)', axes[1, 0]),
            ('avg_payload_size', 'Avg Payload Size (bytes)', axes[1, 1]),
            ('packet_loss_rate', 'Packet Loss Rate (%)', axes[1, 2])
        ]
        
        # Kích thước markers nhỏ cho biểu đồ này
        small_marker_size = 3
        
        for metric, title, ax in metrics_to_plot:
            # Vẽ line plot theo session_id giống performance_trends
            ax.plot(self.origin_df['session_id'], self.origin_df[metric], 
                   marker=marker_style_origin, label='Origin', color=color_origin, 
                   linewidth=line_width, markersize=small_marker_size,
                   markeredgecolor='black', markeredgewidth=0.5, linestyle='-', alpha=0.8)
            ax.plot(self.stego_df['session_id'], self.stego_df[metric],
                   marker=marker_style_stego, label='Stego', color=color_stego,
                   linewidth=line_width, markersize=small_marker_size,
                   markeredgecolor='black', markeredgewidth=0.5, linestyle='-', alpha=0.8)
            
            ax.set_xlabel('Session ID', fontsize=11)
            ax.set_ylabel(title, fontsize=11)
            ax.set_title(title, fontsize=12, fontweight='bold')
            ax.legend(fontsize=10, loc='best')
            ax.grid(True, alpha=0.3, linestyle='--')
        
        plt.tight_layout()
        plt.savefig(output_dir / 'comparison_main_metrics.png', dpi=300, bbox_inches='tight')
        print(f"Đã lưu: {output_dir / 'comparison_main_metrics.png'}")
        plt.close()
        
        # 2. Biểu đồ đường phân bố throughput (density plot)
        fig, axes = plt.subplots(1, 2, figsize=(16, 6))
        fig.suptitle('Phân bố Throughput', fontsize=14, fontweight='bold')
        
        # Tính density cho Origin
        origin_throughput = self.origin_df['throughput_mbps'].sort_values()
        origin_counts, origin_bins = np.histogram(origin_throughput, bins=30)
        origin_bin_centers = (origin_bins[:-1] + origin_bins[1:]) / 2
        origin_density = origin_counts / origin_counts.sum()
        
        # Tính density cho Stego
        stego_throughput = self.stego_df['throughput_mbps'].sort_values()
        stego_counts, stego_bins = np.histogram(stego_throughput, bins=30)
        stego_bin_centers = (stego_bins[:-1] + stego_bins[1:]) / 2
        stego_density = stego_counts / stego_counts.sum()
        
        # Vẽ biểu đồ đường
        axes[0].plot(origin_bin_centers, origin_density, 
                    marker=marker_style_origin, markersize=marker_size-2,
                    color=color_origin, label='Origin', linewidth=line_width,
                    markeredgecolor='black', markeredgewidth=1.2, linestyle='-')
        axes[0].fill_between(origin_bin_centers, origin_density, alpha=0.3, color=color_origin)
        axes[0].set_xlabel('Throughput (Mbps)', fontsize=11)
        axes[0].set_ylabel('Density', fontsize=11)
        axes[0].set_title('Origin Image', fontsize=12, fontweight='bold')
        axes[0].legend(fontsize=10)
        axes[0].grid(True, alpha=0.3, linestyle='--')
        
        axes[1].plot(stego_bin_centers, stego_density,
                    marker=marker_style_stego, markersize=marker_size-2,
                    color=color_stego, label='Stego', linewidth=line_width,
                    markeredgecolor='black', markeredgewidth=1.2, linestyle='-')
        axes[1].fill_between(stego_bin_centers, stego_density, alpha=0.3, color=color_stego)
        axes[1].set_xlabel('Throughput (Mbps)', fontsize=11)
        axes[1].set_ylabel('Density', fontsize=11)
        axes[1].set_title('Stego Image', fontsize=12, fontweight='bold')
        axes[1].legend(fontsize=10)
        axes[1].grid(True, alpha=0.3, linestyle='--')
        
        plt.tight_layout()
        plt.savefig(output_dir / 'throughput_distribution.png', dpi=300, bbox_inches='tight')
        print(f"Đã lưu: {output_dir / 'throughput_distribution.png'}")
        plt.close()
        
        # 3. Biểu đồ xu hướng qua các sessions (markers nhỏ)
        fig, axes = plt.subplots(2, 2, figsize=(16, 10))
        fig.suptitle('Xu hướng Performance qua các Sessions', fontsize=14, fontweight='bold')
        
        # Kích thước markers nhỏ cho biểu đồ này
        very_small_marker_size = 2
        
        # Throughput trend
        axes[0, 0].plot(self.origin_df['session_id'], self.origin_df['throughput_mbps'], 
                       marker=marker_style_origin, label='Origin', color=color_origin, 
                       linewidth=line_width, markersize=very_small_marker_size,
                       markeredgecolor='black', markeredgewidth=0.3, linestyle='-', alpha=0.8)
        axes[0, 0].plot(self.stego_df['session_id'], self.stego_df['throughput_mbps'],
                       marker=marker_style_stego, label='Stego', color=color_stego,
                       linewidth=line_width, markersize=very_small_marker_size,
                       markeredgecolor='black', markeredgewidth=0.3, linestyle='-', alpha=0.8)
        axes[0, 0].set_xlabel('Session ID', fontsize=11)
        axes[0, 0].set_ylabel('Throughput (Mbps)', fontsize=11)
        axes[0, 0].set_title('Throughput Trend', fontsize=12, fontweight='bold')
        axes[0, 0].legend(fontsize=10)
        axes[0, 0].grid(True, alpha=0.3, linestyle='--')
        
        # Transfer time trend
        axes[0, 1].plot(self.origin_df['session_id'], self.origin_df['transfer_time'],
                       marker=marker_style_origin, label='Origin', color=color_origin,
                       linewidth=line_width, markersize=very_small_marker_size,
                       markeredgecolor='black', markeredgewidth=0.3, linestyle='-', alpha=0.8)
        axes[0, 1].plot(self.stego_df['session_id'], self.stego_df['transfer_time'],
                       marker=marker_style_stego, label='Stego', color=color_stego,
                       linewidth=line_width, markersize=very_small_marker_size,
                       markeredgecolor='black', markeredgewidth=0.3, linestyle='-', alpha=0.8)
        axes[0, 1].set_xlabel('Session ID', fontsize=11)
        axes[0, 1].set_ylabel('Transfer Time (s)', fontsize=11)
        axes[0, 1].set_title('Transfer Time Trend', fontsize=12, fontweight='bold')
        axes[0, 1].legend(fontsize=10)
        axes[0, 1].grid(True, alpha=0.3, linestyle='--')
        
        # Packet count trend
        axes[1, 0].plot(self.origin_df['session_id'], self.origin_df['total_packets'],
                       marker=marker_style_origin, label='Origin', color=color_origin,
                       linewidth=line_width, markersize=very_small_marker_size,
                       markeredgecolor='black', markeredgewidth=0.3, linestyle='-', alpha=0.8)
        axes[1, 0].plot(self.stego_df['session_id'], self.stego_df['total_packets'],
                       marker=marker_style_stego, label='Stego', color=color_stego,
                       linewidth=line_width, markersize=very_small_marker_size,
                       markeredgecolor='black', markeredgewidth=0.3, linestyle='-', alpha=0.8)
        axes[1, 0].set_xlabel('Session ID', fontsize=11)
        axes[1, 0].set_ylabel('Total Packets', fontsize=11)
        axes[1, 0].set_title('Packet Count Trend', fontsize=12, fontweight='bold')
        axes[1, 0].legend(fontsize=10)
        axes[1, 0].grid(True, alpha=0.3, linestyle='--')
        
        # Payload size trend
        axes[1, 1].plot(self.origin_df['session_id'], self.origin_df['payload_bytes'],
                       marker=marker_style_origin, label='Origin', color=color_origin,
                       linewidth=line_width, markersize=very_small_marker_size,
                       markeredgecolor='black', markeredgewidth=0.3, linestyle='-', alpha=0.8)
        axes[1, 1].plot(self.stego_df['session_id'], self.stego_df['payload_bytes'],
                       marker=marker_style_stego, label='Stego', color=color_stego,
                       linewidth=line_width, markersize=very_small_marker_size,
                       markeredgecolor='black', markeredgewidth=0.3, linestyle='-', alpha=0.8)
        axes[1, 1].set_xlabel('Session ID', fontsize=11)
        axes[1, 1].set_ylabel('Payload Size (bytes)', fontsize=11)
        axes[1, 1].set_title('Payload Size Trend', fontsize=12, fontweight='bold')
        axes[1, 1].legend(fontsize=10)
        axes[1, 1].grid(True, alpha=0.3, linestyle='--')
        
        plt.tight_layout()
        plt.savefig(output_dir / 'performance_trends.png', dpi=300, bbox_inches='tight')
        print(f"Đã lưu: {output_dir / 'performance_trends.png'}")
        plt.close()
        
        # 4. Biểu đồ cột so sánh (thay thế box plot)
        fig, axes = plt.subplots(2, 3, figsize=(18, 10))
        fig.suptitle('So sánh Origin vs Stego - Biểu đồ Cột', fontsize=14, fontweight='bold')
        
        metrics_for_bar = [
            ('throughput_mbps', 'Throughput (Mbps)', axes[0, 0]),
            ('transfer_time', 'Transfer Time (s)', axes[0, 1]),
            ('total_packets', 'Total Packets', axes[0, 2]),
            ('payload_bytes', 'Payload Size (bytes)', axes[1, 0]),
            ('packet_loss_rate', 'Packet Loss Rate (%)', axes[1, 1]),
            ('avg_latency_ms', 'Avg Latency (ms)', axes[1, 2])
        ]
        
        for metric, title, ax in metrics_for_bar:
            origin_data = self.origin_df[metric]
            stego_data = self.stego_df[metric]
            
            x = np.arange(2)
            width = 0.35  # Độ rộng của cột
            
            origin_mean = origin_data.mean()
            origin_std = origin_data.std()
            stego_mean = stego_data.mean()
            stego_std = stego_data.std()
            
            # Vẽ biểu đồ cột với 2 cột cạnh nhau
            bars1 = ax.bar(x - width/2, [origin_mean], width, 
                          label='Origin', color=color_origin, alpha=0.8,
                          yerr=[origin_std], capsize=5, edgecolor='black', linewidth=1.5)
            bars2 = ax.bar(x + width/2, [stego_mean], width,
                          label='Stego', color=color_stego, alpha=0.8,
                          yerr=[stego_std], capsize=5, edgecolor='black', linewidth=1.5)
            
            ax.set_ylabel(title, fontsize=11)
            ax.set_title(title, fontsize=12, fontweight='bold')
            ax.set_xticks(x)
            ax.set_xticklabels(['Origin', 'Stego'], fontsize=10)
            ax.legend(fontsize=10, loc='best')
            ax.grid(True, alpha=0.3, linestyle='--', axis='y')
        
        plt.tight_layout()
        plt.savefig(output_dir / 'boxplot_comparison.png', dpi=300, bbox_inches='tight')
        print(f"Đã lưu: {output_dir / 'boxplot_comparison.png'}")
        plt.close()


def main():
    """Hàm main"""
    import sys
    
    # Đường dẫn mặc định
    base_dir = Path(__file__).parent
    pairing_csv = base_dir / "Pi5XCom.csv"
    output_dir = base_dir / "Pi5XCom_Result"
    
    # Kiểm tra file tồn tại
    if not pairing_csv.exists():
        print(f"ERROR: Không tìm thấy file {pairing_csv}")
        print("Vui lòng đảm bảo file Pairing.csv tồn tại trong thư mục wifi_benchmark/")
        sys.exit(1)
    
    print("=" * 80)
    print("PHÂN TÍCH WIFI BENCHMARK - ORIGIN vs STEGO")
    print("=" * 80)
    
    # Đọc và phân tích file Pairing.csv
    print("\n[1/4] Đọc và phân tích file Pairing.csv...")
    analyzer = WiresharkAnalyzer(str(pairing_csv))
    analyzer.load_data()
    analyzer.extract_sessions()
    
    # Tách sessions thành origin và stego
    print("\n[2/4] Tách sessions thành Origin và Stego...")
    origin_sessions, stego_sessions = analyzer.split_sessions_by_type()
    print(f"   Tìm thấy {len(origin_sessions)} sessions Origin")
    print(f"   Tìm thấy {len(stego_sessions)} sessions Stego")
    
    # Phân tích Origin sessions
    print("\n[3/4] Phân tích Origin sessions...")
    analyzer.sessions = origin_sessions
    origin_results = analyzer.analyze_all_sessions()
    print(f"   Đã phân tích {len(origin_results)} sessions Origin")
    
    # Phân tích Stego sessions
    print("\n[4/5] Phân tích Stego sessions...")
    analyzer.sessions = stego_sessions
    stego_results = analyzer.analyze_all_sessions()
    print(f"   Đã phân tích {len(stego_results)} sessions Stego")
    
    # So sánh
    print("\n[5/6] So sánh kết quả...")
    comparator = BenchmarkComparator(origin_results, stego_results)
    
    # Tạo bảng so sánh
    comparison_table = comparator.create_comparison_table()
    print("\n" + "=" * 80)
    print("BẢNG SO SÁNH")
    print("=" * 80)
    print(comparison_table.to_string(index=False))
    
    # Lưu bảng so sánh
    output_dir.mkdir(exist_ok=True, parents=True)
    comparison_table.to_csv(output_dir / "comparison_table.csv", index=False)
    print(f"\nĐã lưu bảng so sánh: {output_dir / 'comparison_table.csv'}")
    
    # Lưu kết quả chi tiết
    with open(output_dir / "origin_results.json", 'w', encoding='utf-8') as f:
        json.dump(origin_results, f, indent=2, default=str)
    with open(output_dir / "stego_results.json", 'w', encoding='utf-8') as f:
        json.dump(stego_results, f, indent=2, default=str)
    print(f"Đã lưu kết quả chi tiết: {output_dir / 'origin_results.json'}, {output_dir / 'stego_results.json'}")
    
    # Vẽ biểu đồ
    print("\n[6/6] Vẽ biểu đồ...")
    comparator.plot_comparison(output_dir)
    
    print("\n" + "=" * 80)
    print("HOÀN THÀNH!")
    print("=" * 80)
    print(f"Tất cả kết quả đã được lưu trong: {output_dir}")
    print("\nCác file đã tạo:")
    print("  - comparison_table.csv: Bảng so sánh")
    print("  - comparison_main_metrics.png: Biểu đồ metrics chính")
    print("  - throughput_distribution.png: Phân bố throughput")
    print("  - performance_trends.png: Xu hướng performance")
    print("  - boxplot_comparison.png: Box plot so sánh")
    print("  - origin_results.json: Kết quả chi tiết Origin")
    print("  - stego_results.json: Kết quả chi tiết Stego")


if __name__ == "__main__":
    main()

