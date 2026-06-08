#!/bin/bash
# Railway 启动前数据恢复脚本
# 查找并修复因 CLI 路径 Bug 导致放错位置的数据库和图片

set -e

DATA_DIR="/data"

echo "[restore] Scanning for misplaced database files..."

# 在卷中查找所有 .db 文件，排除空的/.trash 等
found_db=$(find "$DATA_DIR" -maxdepth 8 -name "thyroid_quiz.db" -not -path "*/trash/*" 2>/dev/null | head -5)

for db in $found_db; do
    db_size=$(stat -c%s "$db" 2>/dev/null)
    if [ "$db_size" -gt 100000 ] && [ "$db" != "$DATA_DIR/thyroid_quiz.db" ]; then
        echo "[restore] Found valid DB at: $db (${db_size} bytes)"
        echo "[restore] Moving to $DATA_DIR/thyroid_quiz.db"
        cp -f "$db" "$DATA_DIR/thyroid_quiz.db"
        echo "[restore] Database restored successfully"
    fi
done

echo "[restore] Scanning for images archive..."
found_tar=$(find "$DATA_DIR" -maxdepth 8 -name "*.tar.gz" -not -path "*/trash/*" 2>/dev/null | head -5)

for tarfile in $found_tar; do
    if [ "$(stat -c%s "$tarfile" 2>/dev/null)" -gt 1000000 ]; then
        echo "[restore] Found tar at: $tarfile"
        mkdir -p "$DATA_DIR/storage/images"
        echo "[restore] Extracting images..."
        tar -xzf "$tarfile" -C "$DATA_DIR/"
        rm -f "$tarfile"
        img_count=$(find "$DATA_DIR/storage/images" -type f 2>/dev/null | wc -l)
        echo "[restore] Extracted $img_count images"
    fi
done

# Clean up any directory junk created by path bug
echo "[restore] Cleanup complete"
