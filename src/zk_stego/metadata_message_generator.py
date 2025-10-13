"""
Metadata Message Generator for ZK-SNARK Steganography
Generates natural-looking messages from image metadata for embedding
"""

import hashlib
import json
from datetime import datetime
from typing import Dict, List, Optional, Any
from PIL import Image
from PIL.ExifTags import TAGS
import os


class MetadataMessageGenerator:
    """Generate messages from image metadata for steganographic embedding"""
    
    def __init__(self):
        self.metadata_types = [
            "exif_info",
            "file_properties", 
            "processing_history",
            "authenticity_hash",
            "custom_metadata"
        ]
    
    def extract_exif_metadata(self, image_path: str) -> Dict[str, Any]:
        """Extract EXIF metadata from image"""
        try:
            image = Image.open(image_path)
            exifdata = image.getexif()
            
            metadata = {}
            for tag_id, value in exifdata.items():
                tag = TAGS.get(tag_id, tag_id)
                metadata[tag] = str(value)
                
            return metadata
        except Exception as e:
            print(f"EXIF extraction failed: {e}")
            return {}
    
    def generate_file_properties_message(self, image_path: str) -> str:
        """Generate message from file properties"""
        try:
            stat = os.stat(image_path)
            file_size = stat.st_size
            created_time = datetime.fromtimestamp(stat.st_ctime)
            modified_time = datetime.fromtimestamp(stat.st_mtime)
            
            message = f"File: {os.path.basename(image_path)}, "
            message += f"Size: {file_size} bytes, "
            message += f"Created: {created_time.strftime('%Y-%m-%d %H:%M:%S')}, "
            message += f"Modified: {modified_time.strftime('%Y-%m-%d %H:%M:%S')}"
            
            return message
        except Exception as e:
            return f"File properties extraction failed: {e}"
    
    def generate_camera_info_message(self, exif_data: Dict[str, Any]) -> str:
        """Generate camera information message"""
        camera_fields = [
            ("Make", "Camera Make"),
            ("Model", "Camera Model"), 
            ("DateTime", "Capture Time"),
            ("ISOSpeedRatings", "ISO"),
            ("FNumber", "Aperture"),
            ("ExposureTime", "Shutter Speed"),
            ("FocalLength", "Focal Length")
        ]
        
        message_parts = []
        for field, description in camera_fields:
            if field in exif_data:
                value = exif_data[field]
                message_parts.append(f"{description}: {value}")
        
        if message_parts:
            return "Camera Info - " + ", ".join(message_parts)
        else:
            return "Camera Info - No EXIF data available"
    
    def generate_authenticity_hash_message(self, image_path: str) -> str:
        """Generate authenticity hash message"""
        try:
            # Hash of original file
            with open(image_path, 'rb') as f:
                file_hash = hashlib.sha256(f.read()).hexdigest()
            
            # Timestamp for when hash was created
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            message = f"Authenticity Hash - SHA256: {file_hash[:16]}..., "
            message += f"Verified: {timestamp}"
            
            return message
        except Exception as e:
            return f"Authenticity hash generation failed: {e}"
    
    def generate_processing_history_message(self, custom_info: Optional[str] = None) -> str:
        """Generate processing history message"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        if custom_info:
            message = f"Processing History - {custom_info}, "
        else:
            message = "Processing History - Original image processed with ZK-Steganography, "
            
        message += f"Processed: {timestamp}, "
        message += "Tools: Python PIL + ZK-SNARK circuits, "
        message += "Algorithm: Chaos-based LSB embedding"
        
        return message
    
    def generate_copyright_message(self, author: str, license_type: str = "All Rights Reserved") -> str:
        """Generate copyright protection message"""
        year = datetime.now().year
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        message = f"Copyright (c) {year} {author}. {license_type}. "
        message += f"Protected: {timestamp}. "
        message += "Verified with ZK-SNARK proof. Unauthorized use prohibited."
        
        return message
    
    def generate_location_message(self, latitude: float, longitude: float, 
                                location_name: Optional[str] = None) -> str:
        """Generate location-based message"""
        message = f"Location - GPS: {latitude:.6f}, {longitude:.6f}"
        
        if location_name:
            message += f", Place: {location_name}"
            
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        message += f", Recorded: {timestamp}"
        
        return message
    
    def auto_generate_metadata_message(self, image_path: str, 
                                     message_type: str = "comprehensive") -> str:
        """Automatically generate metadata message from image"""
        
        if message_type == "exif_only":
            exif_data = self.extract_exif_metadata(image_path)
            return self.generate_camera_info_message(exif_data)
            
        elif message_type == "file_properties":
            return self.generate_file_properties_message(image_path)
            
        elif message_type == "authenticity":
            return self.generate_authenticity_hash_message(image_path)
            
        elif message_type == "comprehensive":
            # Combine multiple metadata sources
            messages = []
            
            # File properties
            file_msg = self.generate_file_properties_message(image_path)
            messages.append(file_msg)
            
            # EXIF info
            exif_data = self.extract_exif_metadata(image_path)
            if exif_data:
                camera_msg = self.generate_camera_info_message(exif_data)
                messages.append(camera_msg)
            
            # Join with separator
            return " | ".join(messages)
        
        else:
            return f"Unknown message type: {message_type}"
    
    def get_message_recommendations(self, image_path: str) -> Dict[str, str]:
        """Get recommended messages for different use cases"""
        
        recommendations = {
            "digital_forensics": self.generate_authenticity_hash_message(image_path),
            "copyright_protection": self.generate_copyright_message("Your Name"),
            "technical_metadata": self.auto_generate_metadata_message(image_path, "comprehensive"),
            "processing_record": self.generate_processing_history_message(),
            "file_integrity": self.generate_file_properties_message(image_path)
        }
        
        return recommendations


def demonstrate_metadata_messages():
    """Demonstrate different metadata message types"""
    
    # Example with test image
    test_image = "examples/testvectors/Lenna_test_image.webp"
    
    generator = MetadataMessageGenerator()
    
    print("METADATA MESSAGE GENERATION DEMO")
    print("=" * 50)
    
    # Get all recommendations
    recommendations = generator.get_message_recommendations(test_image)
    
    for use_case, message in recommendations.items():
        print(f"\n{use_case.upper()}:")
        print(f"Message: {message}")
        print(f"Length: {len(message)} characters")
        print(f"Bits required: {len(message) * 8}")
    
    print("\n" + "=" * 50)
    print("IMPLEMENTATION EXAMPLE:")
    print("=" * 50)
    
    print("""
# Usage in your ZK steganography system:
from src.zk_stego.metadata_message_generator import MetadataMessageGenerator
from src.zk_stego.hybrid_proof_artifact import HybridProofArtifact

# Generate metadata message
generator = MetadataMessageGenerator()
metadata_message = generator.auto_generate_metadata_message(
    "path/to/image.jpg", 
    message_type="authenticity"
)

# Use with ZK steganography 
hybrid = HybridProofArtifact()
stego_result = hybrid.embed_with_proof(
    image_array, 
    metadata_message,  # Use metadata instead of custom text
    chaos_key="metadata_protection_key"
)
    """)


if __name__ == "__main__":
    demonstrate_metadata_messages()