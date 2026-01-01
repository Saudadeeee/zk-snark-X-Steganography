# Production H.264 Motion Vector Extraction Guide

## ⚠️ IMPORTANT: Moving from Demo to Production

This guide helps you extract **real motion vectors** from H.264 bitstreams for production use.

---

## 🎯 Three Production Methods

### Method 1: PyAV (Recommended for Quick Start)
**Pros**: Easy to setup, cross-platform
**Cons**: MV export depends on FFmpeg version, may not work on all systems

### Method 2: Modified FFmpeg (Most Reliable)
**Pros**: Direct access to decoder internals, full control
**Cons**: Requires building custom FFmpeg

### Method 3: JM Reference Decoder (Gold Standard)
**Pros**: Official H.264 reference, complete MV access, best for research
**Cons**: Slower, requires C compilation

---

## 📦 Method 1: PyAV Setup

### 1. Install PyAV

```bash
# Windows
pip install av

# Linux/Mac
pip install av
```

### 2. Test PyAV MV extraction

```bash
cd VideoLevel/tools/mv_extractor
python h264_parser.py ../../TestVideo/foreman_cif.y4m 100
```

### 3. Common Issues

**Issue**: `No motion vectors found`
- PyAV version incompatibility
- FFmpeg library doesn't support `export_mvs`

**Solution**: Use Method 2 or 3

---

## 🔧 Method 2: Custom FFmpeg Build

### Why Custom FFmpeg?

Standard FFmpeg can visualize MVs but doesn't easily export raw MV data.
We need to modify FFmpeg to dump MVs to a structured format.

### Steps:

#### 1. Clone FFmpeg

```bash
git clone https://git.ffmpeg.org/ffmpeg.git
cd ffmpeg
git checkout release/6.0
```

#### 2. Apply MV Export Patch

Create `libavcodec/mv_export.c`:

```c
#include "avcodec.h"
#include "libavutil/motion_vector.h"
#include "libavutil/frame.h"

// Export motion vectors to CSV file
void export_mvs_to_csv(AVFrame *frame, FILE *fp) {
    AVFrameSideData *sd = av_frame_get_side_data(frame, AV_FRAME_DATA_MOTION_VECTORS);
    if (!sd)
        return;

    const AVMotionVector *mvs = (const AVMotionVector *)sd->data;
    int mv_count = sd->size / sizeof(*mvs);

    for (int i = 0; i < mv_count; i++) {
        fprintf(fp, "%d,%d,%d,%d,%d,%d,%d,%d,%d,%d\n",
                mvs[i].source,
                mvs[i].w, mvs[i].h,
                mvs[i].src_x, mvs[i].src_y,
                mvs[i].dst_x, mvs[i].dst_y,
                mvs[i].motion_x, mvs[i].motion_y,
                mvs[i].motion_scale);
    }
}
```

#### 3. Modify `ffmpeg_filter.c` to call export

Add to `do_video_out()`:

```c
if (export_mvs_file) {
    export_mvs_to_csv(frame, export_mvs_file);
}
```

#### 4. Build FFmpeg

```bash
# Configure with necessary libraries
./configure --enable-gpl --enable-libx264 --enable-nonfree

# Build
make -j8

# Install
sudo make install
```

#### 5. Use Custom FFmpeg

```bash
ffmpeg -flags2 +export_mvs -i input.mp4 -export_mvs mvs.csv -f null -
```

---

## 🥇 Method 3: JM Reference Decoder (Recommended for Research)

### Why JM?

JM (Joint Model) is the official H.264/AVC reference software. It provides:
- Complete access to all decoder internals
- Motion Vector Difference (MVD) access
- MVP (Motion Vector Predictor) access
- Full control over output format

### Download JM

#### Option A: Official Source

```bash
# From ITU-T
wget https://vcgit.hhi.fraunhofer.de/jvet/JM/-/archive/JM-19.0/JM-JM-19.0.tar.gz
tar -xzf JM-JM-19.0.tar.gz
cd JM-JM-19.0
```

#### Option B: GitHub Mirror

```bash
git clone https://github.com/Distrotech/JM.git
cd JM
```

### Build JM Decoder

#### Windows (Visual Studio)

```bash
# Open JM/vc10.sln in Visual Studio
# Select 'ldecod' project
# Build -> Build Solution (Release x64)
# Output: JM/bin/ldecod.exe
```

#### Linux/Mac

```bash
cd lencod
make
cd ../ldecod
make
```

### Modify JM to Export MVs

#### 1. Edit `ldecod/src/block.c`

Add MV export function:

```c
FILE *mv_export_file = NULL;

void export_motion_vector(int frame_num, int mb_x, int mb_y, 
                          int mvx, int mvy, int mvd_x, int mvd_y) {
    if (!mv_export_file) {
        mv_export_file = fopen("mv_export.csv", "w");
        fprintf(mv_export_file, "frame,mb_x,mb_y,mvx,mvy,mvd_x,mvd_y\n");
    }
    
    fprintf(mv_export_file, "%d,%d,%d,%d,%d,%d,%d\n",
            frame_num, mb_x, mb_y, mvx, mvy, mvd_x, mvd_y);
    fflush(mv_export_file);
}
```

#### 2. Call export in MB decoding

In `decode_one_macroblock()`:

```c
// After MV reconstruction
if (currMB->mb_type == P16x16 || currMB->mb_type == P16x8 || ...) {
    int mvx = currMB->mvd[LIST_0][block][0][0];
    int mvy = currMB->mvd[LIST_0][block][0][1];
    
    export_motion_vector(img->frame_num, currMB->mb_x, currMB->mb_y,
                        mvx, mvy, mvd_x, mvd_y);
}
```

#### 3. Rebuild JM

```bash
cd ldecod
make clean
make
```

#### 4. Run Modified Decoder

```bash
# Convert video to H.264 bitstream
ffmpeg -i input.mp4 -c:v copy -f h264 test.264

# Decode with MV export
./ldecod -i test.264 -o output.yuv

# MVs exported to mv_export.csv
```

### Parse JM CSV Output

```python
import pandas as pd

# Load exported MVs
mvs = pd.read_csv('mv_export.csv')

# Filter P-frame MVs with non-zero motion
p_mvs = mvs[(mvs['mvx'] != 0) | (mvs['mvy'] != 0)]

print(f"Total MVs: {len(mvs)}")
print(f"P-frame MVs: {len(p_mvs)}")
print(f"Capacity: {len(p_mvs) * 2} bits")
```

---

## 🚀 Quick Start (Choose Your Path)

### For Development/Testing (Quick)
→ Use **Method 1 (PyAV)** with `h264_parser.py`

### For Production (Reliable)
→ Use **Method 3 (JM Reference)** with modified decoder

### For Advanced Control
→ Use **Method 2 (Custom FFmpeg)** build

---

## 📊 Validation

After extracting real MVs, validate with:

```bash
# Run Phase 0 with real data
python phase0_demo.py TestVideo/foreman_cif.y4m --use-real-parser

# Check output statistics
cat results/stats/*/statistics.json
```

Expected output:
- ✅ Non-uniform MV distribution (not synthetic)
- ✅ P-frame MVs > 0
- ✅ Realistic magnitude range (not random)
- ✅ Spatial/temporal correlation visible

---

## 🔍 Troubleshooting

### PyAV: "No attribute 'motion_vectors'"
→ FFmpeg version too old, use JM instead

### JM: Compile errors on Windows
→ Use Visual Studio 2019+, install Windows SDK

### FFmpeg: MVs not exported
→ Check FFmpeg build: `ffmpeg -version` should show `--enable-libavcodec`

---

## 📝 Next Steps

Once you have real MV extraction working:

1. ✅ Run Phase 0 analysis with real data
2. ✅ Verify parity distribution is natural (not 50/50)
3. ✅ Measure real capacity estimates
4. ✅ Proceed to Phase 1: Encoder modification

---

## 📚 References

- PyAV docs: https://pyav.org/docs/stable/
- FFmpeg source: https://git.ffmpeg.org/ffmpeg.git
- JM reference: https://vcgit.hhi.fraunhofer.de/jvet/JM
- H.264 spec: ITU-T Recommendation H.264

---

**Status**: Ready for production H.264 MV extraction
**Last Updated**: 2026-01-01
