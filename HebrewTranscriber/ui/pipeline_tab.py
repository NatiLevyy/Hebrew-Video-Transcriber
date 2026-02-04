"""
Complete Automated Pipeline Tab - One-click workflow from NotebookLM to embedded videos.

User does:
1. Select output folder
2. Login to NotebookLM
3. Select notebooks
4. Click START

System does automatically:
Scan → Download → Transcribe → RTL Fix → Embed
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QProgressBar, QTextEdit, QGroupBox,
    QFileDialog, QMessageBox, QCheckBox, QListWidget,
    QListWidgetItem, QSplitter, QScrollArea, QLineEdit,
    QDialog, QTreeWidget, QTreeWidgetItem
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSettings
from pathlib import Path
import os
import re

from core.transcriber import HebrewTranscriber
from core.audio_extractor import AudioExtractor
from core.exporter import (
    SRTExporter, find_all_srts, find_all_srts_multi,
    export_srt_to_md, export_srt_to_pdf,
    merge_srts_to_md, merge_srts_to_pdf
)
from core.subtitle_embedder import embed_subtitles, is_mkvmerge_available, VIDEO_FORMATS
from core.mp4_converter import convert_to_mp4, is_ffmpeg_available
from core.notebooklm_downloader import (
    NotebookLMDownloader, NotebookInfo, DownloadProgress
)
from core.google_drive import GoogleDriveUploader, is_google_api_available


class FolderPickerDialog(QDialog):
    """Custom multi-folder picker using QTreeWidget.
    Supports Ctrl+Click and Shift+Click for multi-selection,
    just like Windows File Explorer. Loads subfolders lazily on expand.
    """

    def __init__(self, parent=None, start_path=None):
        super().__init__(parent)
        self.setWindowTitle("Select Folders (Ctrl+Click / Shift+Click)")
        self.setMinimumSize(750, 550)

        layout = QVBoxLayout(self)

        # Info label
        info = QLabel("Navigate and select folders using Ctrl+Click or Shift+Click:")
        info.setStyleSheet("font-size: 13px; font-weight: bold;")
        layout.addWidget(info)

        # Tree widget with multi-selection (no QFileSystemModel needed)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setSelectionMode(
            QTreeWidget.SelectionMode.ExtendedSelection
        )
        self.tree.setAnimated(True)
        self.tree.itemExpanded.connect(self._on_expand)

        # Populate drive roots (Windows) or filesystem root
        self._populate_roots()

        # Navigate to start path if provided
        if start_path:
            self._navigate_to(start_path)

        layout.addWidget(self.tree)

        # Selection count
        self.sel_label = QLabel("0 folders selected")
        self.sel_label.setStyleSheet("color: #666; font-size: 12px;")
        layout.addWidget(self.sel_label)
        self.tree.itemSelectionChanged.connect(self._update_sel_count)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet("padding: 8px 20px; font-size: 13px;")
        cancel_btn.clicked.connect(self.reject)
        add_btn = QPushButton("Add Selected Folders")
        add_btn.setStyleSheet(
            "padding: 8px 20px; font-size: 13px; font-weight: bold; "
            "background-color: #4CAF50; color: white; border-radius: 4px;"
        )
        add_btn.clicked.connect(self.accept)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(add_btn)
        layout.addLayout(btn_row)

    def _populate_roots(self):
        """Add drive letters (Windows) or '/' as root nodes."""
        import string
        if os.name == 'nt':
            for letter in string.ascii_uppercase:
                drive = f"{letter}:\\"
                if Path(drive).exists():
                    item = QTreeWidgetItem(self.tree, [f"{letter}:"])
                    item.setData(0, Qt.ItemDataRole.UserRole, drive)
                    # Add placeholder child so the expand arrow appears
                    QTreeWidgetItem(item, ["..."])
        else:
            item = QTreeWidgetItem(self.tree, ["/"])
            item.setData(0, Qt.ItemDataRole.UserRole, "/")
            QTreeWidgetItem(item, ["..."])

    def _on_expand(self, item: QTreeWidgetItem):
        """Lazily load subfolders when a node is expanded."""
        # Check if this node still has the placeholder
        if item.childCount() == 1 and item.child(0).text(0) == "...":
            item.removeChild(item.child(0))
            folder_path = item.data(0, Qt.ItemDataRole.UserRole)
            self._load_children(item, folder_path)

    def _load_children(self, parent_item: QTreeWidgetItem, folder_path: str):
        """Read subfolders from disk and add them as children."""
        try:
            p = Path(folder_path)
            subdirs = sorted(
                [d for d in p.iterdir() if d.is_dir() and not d.name.startswith('.')],
                key=lambda d: [int(c) if c.isdigit() else c.lower()
                               for c in re.split(r'(\d+)', d.name)]
            )
            for sub in subdirs:
                child = QTreeWidgetItem(parent_item, [sub.name])
                child.setData(0, Qt.ItemDataRole.UserRole, str(sub))
                # Add placeholder so it can be expanded further
                QTreeWidgetItem(child, ["..."])
        except PermissionError:
            pass

    def _navigate_to(self, target_path: str):
        """Expand the tree down to the given path and select it."""
        parts = Path(target_path).parts
        if not parts:
            return
        # Find root item
        root_text = parts[0].rstrip("\\").rstrip("/")
        if os.name == 'nt' and len(root_text) == 2 and root_text[1] == ':':
            root_text = root_text  # e.g. "C:"
        current = None
        for i in range(self.tree.topLevelItemCount()):
            if self.tree.topLevelItem(i).text(0) == root_text:
                current = self.tree.topLevelItem(i)
                break
        if not current:
            return
        # Expand down the path
        for part in parts[1:]:
            self.tree.expandItem(current)
            found = False
            for ci in range(current.childCount()):
                if current.child(ci).text(0) == part:
                    current = current.child(ci)
                    found = True
                    break
            if not found:
                break
        self.tree.scrollToItem(current)
        current.setSelected(True)

    def _update_sel_count(self):
        count = len(self.get_selected_folders())
        self.sel_label.setText(f"{count} folder(s) selected")

    def get_selected_folders(self) -> list:
        """Return list of selected folder path strings."""
        items = self.tree.selectedItems()
        paths = []
        for item in items:
            path = item.data(0, Qt.ItemDataRole.UserRole)
            if path:
                paths.append(path)
        return sorted(paths)


class MergeSRTDialog(QDialog):
    """Dialog for merging SRT files from multiple folders.

    Uses a 'Scan Parent Folder' approach: user picks a parent directory,
    then all subfolders are shown as checkable items. This works reliably
    on Windows (unlike QFileDialog multi-folder hacks).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Merge SRT Files")
        self.setMinimumWidth(650)
        self.setMinimumHeight(500)
        self.folders = []  # checked folder paths (str)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Info
        info = QLabel(
            "Browse to select folders (Ctrl+Click for multiple), "
            "or Scan Parent to add all subfolders. Check the ones to merge:"
        )
        info.setStyleSheet("font-size: 13px;")
        info.setWordWrap(True)
        layout.addWidget(info)

        # Folder selection buttons
        btn_row = QHBoxLayout()
        browse_btn = QPushButton("📂 Browse & Select Folders")
        browse_btn.setStyleSheet("padding: 8px 14px; font-size: 13px; font-weight: bold;")
        browse_btn.setToolTip("Open folder tree — Ctrl+Click / Shift+Click to pick multiple folders")
        browse_btn.clicked.connect(self.browse_folders)
        scan_btn = QPushButton("⚡ Scan Parent Folder")
        scan_btn.setStyleSheet("padding: 8px; font-size: 13px;")
        scan_btn.setToolTip("Pick a parent folder — all subfolders added automatically")
        scan_btn.clicked.connect(self.scan_parent_folder)
        btn_row.addWidget(browse_btn)
        btn_row.addWidget(scan_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # Select All / Deselect All
        sel_row = QHBoxLayout()
        select_all_btn = QPushButton("Select All")
        select_all_btn.setStyleSheet("padding: 5px 10px; font-size: 12px;")
        select_all_btn.clicked.connect(lambda: self._set_all_checked(True))
        deselect_all_btn = QPushButton("Deselect All")
        deselect_all_btn.setStyleSheet("padding: 5px 10px; font-size: 12px;")
        deselect_all_btn.clicked.connect(lambda: self._set_all_checked(False))
        sel_row.addWidget(select_all_btn)
        sel_row.addWidget(deselect_all_btn)
        sel_row.addStretch()
        layout.addLayout(sel_row)

        # Folder list (checkable items)
        self.folder_list = QListWidget()
        self.folder_list.setMinimumHeight(180)
        self.folder_list.setStyleSheet("font-size: 12px; padding: 4px;")
        layout.addWidget(self.folder_list)

        # SRT count label
        self.srt_count_label = QLabel("")
        self.srt_count_label.setStyleSheet("color: #666; font-size: 12px;")
        layout.addWidget(self.srt_count_label)

        # Title
        title_row = QHBoxLayout()
        title_row.addWidget(QLabel("Document title:"))
        self.title_edit = QLineEdit("Merged Transcriptions")
        self.title_edit.setStyleSheet("padding: 6px; font-size: 13px;")
        title_row.addWidget(self.title_edit)
        layout.addLayout(title_row)

        # Output folder
        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("Save to:"))
        self.output_label = QLabel("(same as first folder)")
        self.output_label.setStyleSheet("color: #666;")
        out_row.addWidget(self.output_label, 1)
        out_browse = QPushButton("Browse...")
        out_browse.clicked.connect(self.browse_output)
        out_row.addWidget(out_browse)
        layout.addLayout(out_row)
        self.output_folder = None

        # Format
        format_row = QHBoxLayout()
        format_row.addWidget(QLabel("Format:"))
        self.md_cb = QCheckBox("Markdown")
        self.md_cb.setChecked(True)
        self.pdf_cb = QCheckBox("PDF")
        self.pdf_cb.setChecked(True)
        format_row.addWidget(self.md_cb)
        format_row.addWidget(self.pdf_cb)
        format_row.addStretch()
        layout.addLayout(format_row)

        # OK / Cancel
        action_row = QHBoxLayout()
        self.merge_btn = QPushButton("Merge")
        self.merge_btn.setStyleSheet(
            "padding: 10px 30px; font-size: 14px; font-weight: bold; "
            "background-color: #4CAF50; color: white; border-radius: 6px;"
        )
        self.merge_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet("padding: 10px 20px; font-size: 13px;")
        cancel_btn.clicked.connect(self.reject)
        action_row.addStretch()
        action_row.addWidget(cancel_btn)
        action_row.addWidget(self.merge_btn)
        layout.addLayout(action_row)

    def scan_parent_folder(self):
        """Pick a parent folder, then list all its subfolders as checkable items."""
        parent = QFileDialog.getExistingDirectory(
            self, "Select parent folder (subfolders will be listed)"
        )
        if not parent:
            return

        parent_path = Path(parent)
        subfolders = sorted(
            [d for d in parent_path.iterdir() if d.is_dir()],
            key=lambda d: [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', d.name)]
        )

        if not subfolders:
            # No subfolders — add the parent itself
            self._add_folder_item(parent)
            self._update_srt_count()
            return

        # Add each subfolder as a checkable item (checked by default)
        added = 0
        for subfolder in subfolders:
            if self._add_folder_item(str(subfolder)):
                added += 1

        if added == 0:
            QMessageBox.information(
                self, "No new folders",
                "All subfolders are already in the list."
            )
        self._update_srt_count()

    def browse_folders(self):
        """Open custom tree-view folder picker with Ctrl/Shift multi-select."""
        picker = FolderPickerDialog(self)
        if picker.exec() == QDialog.DialogCode.Accepted:
            selected = picker.get_selected_folders()
            added = 0
            for folder in selected:
                if self._add_folder_item(folder):
                    added += 1
            if added > 0:
                self._update_srt_count()

    def _add_folder_item(self, folder_path: str) -> bool:
        """Add a checkable folder item to the list. Returns True if added."""
        # Avoid duplicates
        for i in range(self.folder_list.count()):
            if self.folder_list.item(i).data(Qt.ItemDataRole.UserRole) == folder_path:
                return False

        item = QListWidgetItem(Path(folder_path).name)
        item.setToolTip(folder_path)
        item.setData(Qt.ItemDataRole.UserRole, folder_path)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Checked)
        self.folder_list.addItem(item)
        return True

    def _set_all_checked(self, checked: bool):
        """Check or uncheck all folder items."""
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for i in range(self.folder_list.count()):
            self.folder_list.item(i).setCheckState(state)
        self._update_srt_count()

    def _get_checked_folders(self) -> list:
        """Return list of checked folder path strings."""
        result = []
        for i in range(self.folder_list.count()):
            item = self.folder_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                result.append(item.data(Qt.ItemDataRole.UserRole))
        return result

    def browse_output(self):
        folder = QFileDialog.getExistingDirectory(self, "Select output folder")
        if folder:
            self.output_folder = folder
            self.output_label.setText(folder)
            self.output_label.setStyleSheet("color: #333;")

    def _update_srt_count(self):
        checked = self._get_checked_folders()
        total = 0
        for f in checked:
            total += len(find_all_srts(Path(f)))
        self.srt_count_label.setText(
            f"Found {total} SRT files in {len(checked)} checked folders"
        )

    def get_result(self):
        """Return (folders, output_folder, title, do_md, do_pdf)."""
        checked = self._get_checked_folders()
        out = self.output_folder or (checked[0] if checked else None)
        return (
            [Path(f) for f in checked],
            Path(out) if out else None,
            self.title_edit.text().strip() or "Merged Transcriptions",
            self.md_cb.isChecked(),
            self.pdf_cb.isChecked()
        )


# ========== WORKERS ==========

class AuthWorker(QThread):
    """Worker for NotebookLM authentication."""
    status_update = pyqtSignal(str)
    auth_complete = pyqtSignal(bool, object)

    def run(self):
        downloader = NotebookLMDownloader()
        success = downloader.authenticate(self.status_update.emit)
        self.auth_complete.emit(success, downloader if success else None)


class ListNotebooksWorker(QThread):
    """Worker for listing notebooks with caching support."""
    status_update = pyqtSignal(str)
    list_complete = pyqtSignal(list, int)  # notebooks, new_count

    def __init__(self, downloader, force_refresh=False):
        super().__init__()
        self.downloader = downloader
        self.force_refresh = force_refresh

    def run(self):
        notebooks, new_count = self.downloader.list_notebooks_with_cache(
            force_refresh=self.force_refresh,
            on_status=self.status_update.emit
        )
        self.list_complete.emit(notebooks, new_count)


class FullPipelineWorker(QThread):
    """
    Worker that runs the COMPLETE pipeline automatically:
    Scan → Download → Transcribe → RTL Fix → Embed
    """
    log_update = pyqtSignal(str)
    stage_update = pyqtSignal(str, int)  # stage_name, progress_percent
    pipeline_complete = pyqtSignal(dict)

    def __init__(self, downloader, notebooks, output_folder, do_download, do_transcribe, do_embed, do_export_md=False, do_export_pdf=False, do_convert_mp4=False):
        super().__init__()
        self.downloader = downloader
        self.notebooks = notebooks
        self.output_folder = Path(output_folder)
        self.do_download = do_download
        self.do_transcribe = do_transcribe
        self.do_embed = do_embed
        self.do_export_md = do_export_md
        self.do_export_pdf = do_export_pdf
        self.do_convert_mp4 = do_convert_mp4
        self._cancelled = False

    def cancel(self):
        self._cancelled = True
        if self.downloader:
            self.downloader.cancel()

    def run(self):
        results = {
            'scanned': 0,
            'downloaded': 0,
            'transcribed': 0,
            'exported': 0,
            'embedded': 0,
            'rtl_fixed': 0,
            'converted_mp4': 0,
            'errors': []
        }

        try:
            # ===== STAGE 1: SCAN FOR MEDIA =====
            self.log_update.emit("\n" + "=" * 50)
            self.log_update.emit("📡 STAGE 1: SCANNING FOR MEDIA")
            self.log_update.emit("=" * 50)
            self.stage_update.emit("Scanning notebooks...", 5)

            notebooks_with_media = self.downloader.scan_for_media(
                self.notebooks, self.log_update.emit
            )

            if self._cancelled:
                self.pipeline_complete.emit(results)
                return

            if not notebooks_with_media:
                self.log_update.emit("No media found in selected notebooks!")
                self.pipeline_complete.emit(results)
                return

            total_media = sum(
                len(nb.audio_artifacts) + len(nb.video_artifacts)
                for nb in notebooks_with_media
            )
            results['scanned'] = total_media
            self.log_update.emit(f"✓ Found {total_media} media files in {len(notebooks_with_media)} notebooks")

            # ===== STAGE 2: DOWNLOAD =====
            if self.do_download:
                self.log_update.emit("\n" + "=" * 50)
                self.log_update.emit("⬇️ STAGE 2: DOWNLOADING")
                self.log_update.emit("=" * 50)
                self.stage_update.emit("Downloading...", 20)

                self.output_folder.mkdir(parents=True, exist_ok=True)

                downloaded_files = self.downloader.download_artifacts(
                    notebooks_with_media,
                    self.output_folder,
                    download_audio=True,
                    download_video=True,
                    on_progress=lambda p: self.log_update.emit(
                        f"  [{p.current}/{p.total}] {p.current_file}"
                    )
                )

                if self._cancelled:
                    self.pipeline_complete.emit(results)
                    return

                results['downloaded'] = len(downloaded_files)
                self.log_update.emit(f"✓ Downloaded {len(downloaded_files)} files")

            # ===== STAGE 3: TRANSCRIBE =====
            if self.do_transcribe:
                self.log_update.emit("\n" + "=" * 50)
                self.log_update.emit("🎤 STAGE 3: TRANSCRIBING TO HEBREW")
                self.log_update.emit("=" * 50)
                self.stage_update.emit("Loading model...", 40)

                # Find all notebook subfolders
                nb_folders = [
                    f for f in self.output_folder.iterdir()
                    if f.is_dir() and f.name not in ('Subtitle_HEBREW', 'Embedded_Videos')
                ]

                # Collect all video files across notebook folders
                all_videos = []
                for nb_folder in nb_folders:
                    for vf in nb_folder.iterdir():
                        if vf.is_file() and vf.suffix.lower() in VIDEO_FORMATS:
                            all_videos.append((nb_folder, vf))

                if not all_videos:
                    self.log_update.emit("No video files to transcribe")
                else:
                    transcriber = HebrewTranscriber()
                    extractor = AudioExtractor()

                    self.log_update.emit("Loading ivrit-ai/whisper model...")
                    transcriber.load_model()
                    self.log_update.emit(f"Model loaded on {transcriber.device.upper()}")

                    total = len(all_videos)
                    for i, (nb_folder, video_path) in enumerate(all_videos):
                        if self._cancelled:
                            break

                        progress = 40 + int((i / total) * 30)
                        self.stage_update.emit(f"Transcribing {i+1}/{total}...", progress)
                        self.log_update.emit(f"  [{i+1}/{total}] {nb_folder.name}/{video_path.name}")

                        try:
                            audio_path = extractor.extract(str(video_path))
                            segments = transcriber.transcribe(audio_path)
                            Path(audio_path).unlink(missing_ok=True)

                            # Save SRT inside the notebook folder
                            srt_folder = nb_folder / "Subtitle_HEBREW"
                            srt_folder.mkdir(exist_ok=True)

                            srt_path = srt_folder / f"{video_path.stem}.srt"
                            SRTExporter().export(segments, str(srt_path), video_path.stem)

                            results['transcribed'] += 1
                            self.log_update.emit(f"    ✓ {srt_path.name}")

                        except Exception as e:
                            results['errors'].append((video_path.name, str(e)))
                            self.log_update.emit(f"    ✗ Error: {e}")

                    self.log_update.emit(f"✓ Transcribed {results['transcribed']} files")

            # ===== STAGE 3.5: EXPORT SRT TO MD/PDF =====
            if self.do_export_md or self.do_export_pdf:
                self.log_update.emit("\n" + "=" * 50)
                self.log_update.emit("📄 STAGE 3.5: EXPORT SRT TO MD/PDF")
                self.log_update.emit("=" * 50)
                self.stage_update.emit("Exporting SRTs...", 72)

                nb_folders = [
                    f for f in self.output_folder.iterdir()
                    if f.is_dir() and f.name not in ('Subtitle_HEBREW', 'Embedded_Videos', 'Exported')
                ]

                all_srt_files = []
                exported_count = 0

                for nb_folder in nb_folders:
                    srt_folder = nb_folder / "Subtitle_HEBREW"
                    if not srt_folder.exists():
                        continue

                    srt_files = find_all_srts(srt_folder)
                    all_srt_files.extend(srt_files)

                    export_folder = nb_folder / "Exported"
                    export_folder.mkdir(exist_ok=True)

                    for srt_path in srt_files:
                        try:
                            if self.do_export_md:
                                md_path = export_folder / f"{srt_path.stem}.md"
                                export_srt_to_md(srt_path, md_path)
                                self.log_update.emit(f"  ✓ {nb_folder.name}/{md_path.name}")
                                exported_count += 1

                            if self.do_export_pdf:
                                pdf_path = export_folder / f"{srt_path.stem}.pdf"
                                export_srt_to_pdf(srt_path, pdf_path)
                                self.log_update.emit(f"  ✓ {nb_folder.name}/{pdf_path.name}")
                                exported_count += 1
                        except Exception as e:
                            self.log_update.emit(f"  ✗ Export error: {e}")
                            results['errors'].append((srt_path.name, str(e)))

                # Merge all SRTs into one unified document
                if all_srt_files:
                    merge_title = self.output_folder.name or "Merged Transcriptions"
                    self.log_update.emit(f"\n  Merging {len(all_srt_files)} SRT files into one document...")

                    try:
                        if self.do_export_md:
                            merged_md = self.output_folder / f"{merge_title}_MERGED.md"
                            merge_srts_to_md(all_srt_files, merged_md, merge_title)
                            self.log_update.emit(f"  ✓ Merged MD: {merged_md.name}")
                            exported_count += 1

                        if self.do_export_pdf:
                            merged_pdf = self.output_folder / f"{merge_title}_MERGED.pdf"
                            merge_srts_to_pdf(all_srt_files, merged_pdf, merge_title)
                            self.log_update.emit(f"  ✓ Merged PDF: {merged_pdf.name}")
                            exported_count += 1
                    except Exception as e:
                        self.log_update.emit(f"  ✗ Merge error: {e}")
                        results['errors'].append(("Merge", str(e)))

                results['exported'] = exported_count
                self.log_update.emit(f"✓ Exported {exported_count} files")

            # ===== STAGE 4: RTL FIX + EMBED =====
            if self.do_embed and is_mkvmerge_available():
                self.log_update.emit("\n" + "=" * 50)
                self.log_update.emit("📀 STAGE 4: RTL FIX + EMBED SUBTITLES")
                self.log_update.emit("=" * 50)
                self.stage_update.emit("Embedding subtitles...", 75)

                # Process each notebook folder separately
                nb_folders = [
                    f for f in self.output_folder.iterdir()
                    if f.is_dir() and f.name not in ('Subtitle_HEBREW', 'Embedded_Videos')
                ]

                for nb_folder in nb_folders:
                    srt_folder = nb_folder / "Subtitle_HEBREW"
                    embed_folder = nb_folder / "Embedded_Videos"

                    if srt_folder.exists():
                        self.log_update.emit(f"\n--- {nb_folder.name} ---")
                        embed_result = embed_subtitles(
                            video_folder=nb_folder,
                            srt_folder=srt_folder,
                            output_folder=embed_folder,
                            log=self.log_update.emit,
                            skip_existing=True,
                            fix_rtl=True
                        )

                        results['embedded'] += len(embed_result.get('embedded', []))
                        results['rtl_fixed'] += embed_result.get('rtl_fixed', 0)

                if not nb_folders:
                    self.log_update.emit("No notebook folders found, skipping embed")

            # ===== STAGE 5: CONVERT TO MP4 (WhatsApp-ready) =====
            if self.do_convert_mp4:
                self.log_update.emit("\n" + "=" * 50)
                self.log_update.emit("📱 STAGE 5: CONVERT TO MP4 (WhatsApp-ready)")
                self.log_update.emit("=" * 50)
                self.stage_update.emit("Converting to MP4...", 85)

                if self._cancelled:
                    self.pipeline_complete.emit(results)
                    return

                nb_folders = [
                    f for f in self.output_folder.iterdir()
                    if f.is_dir() and f.name not in ('Subtitle_HEBREW', 'Embedded_Videos', 'WhatsApp_Videos', 'Exported')
                ]

                for nb_folder in nb_folders:
                    srt_folder = nb_folder / "Subtitle_HEBREW"
                    mp4_folder = nb_folder / "WhatsApp_Videos"

                    if srt_folder.exists():
                        self.log_update.emit(f"\n--- {nb_folder.name} ---")
                        mp4_result = convert_to_mp4(
                            video_folder=nb_folder,
                            srt_folder=srt_folder,
                            output_folder=mp4_folder,
                            log=self.log_update.emit,
                            skip_existing=True,
                            fix_rtl=True
                        )

                        results['converted_mp4'] += len(mp4_result.get('converted', []))

                if not nb_folders:
                    self.log_update.emit("No notebook folders found, skipping MP4 conversion")

            # ===== COMPLETE =====
            self.stage_update.emit("Complete!", 100)
            self.log_update.emit("\n" + "=" * 50)
            self.log_update.emit("✅ PIPELINE COMPLETE!")
            self.log_update.emit("=" * 50)
            self.log_update.emit(f"  Scanned: {results['scanned']} media files")
            self.log_update.emit(f"  Downloaded: {results['downloaded']} files")
            self.log_update.emit(f"  Transcribed: {results['transcribed']} files")
            self.log_update.emit(f"  Exported: {results['exported']} files")
            self.log_update.emit(f"  RTL Fixed: {results['rtl_fixed']} lines")
            self.log_update.emit(f"  Embedded: {results['embedded']} videos")
            if results['converted_mp4'] > 0:
                self.log_update.emit(f"  MP4 (WhatsApp): {results['converted_mp4']} videos")

            if results['errors']:
                self.log_update.emit(f"  Errors: {len(results['errors'])}")

        except Exception as e:
            self.log_update.emit(f"\n❌ Pipeline error: {e}")
            results['errors'].append(("Pipeline", str(e)))

        self.pipeline_complete.emit(results)


class DriveUploadWorker(QThread):
    """Worker for uploading files to Google Drive."""
    status_update = pyqtSignal(str)
    progress_update = pyqtSignal(int, int, str, int)  # current, total, filename, percent
    upload_complete = pyqtSignal(dict)

    def __init__(self, uploader, files):
        super().__init__()
        self.uploader = uploader
        self.files = files  # List of (local_path, notebook_name)

    def run(self):
        self.status_update.emit(f"Uploading {len(self.files)} files to Google Drive...")
        results = self.uploader.upload_files(
            self.files,
            on_progress=lambda c, t, f, p: self.progress_update.emit(c, t, f, p)
        )
        self.upload_complete.emit(results)


class DriveUploadDialog(QDialog):
    """Dialog for selecting files to upload to Google Drive."""

    def __init__(self, output_folder: Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Upload to Google Drive")
        self.setMinimumWidth(600)
        self.setMinimumHeight(500)
        self.output_folder = output_folder
        self.selected_files = []  # List of (path, notebook_name)

        self.init_ui()
        self.scan_files()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Info
        info = QLabel(
            "Select files to upload to Google Drive.\n"
            "Files will be organized as: HebrewTranscriber/YYYY-MM/[Notebook]/[files]"
        )
        info.setStyleSheet("font-size: 12px; color: #666;")
        info.setWordWrap(True)
        layout.addWidget(info)

        # Select all / deselect all
        btn_row = QHBoxLayout()
        select_all = QPushButton("Select All")
        select_all.clicked.connect(lambda: self._set_all_checked(True))
        deselect_all = QPushButton("Deselect All")
        deselect_all.clicked.connect(lambda: self._set_all_checked(False))
        btn_row.addWidget(select_all)
        btn_row.addWidget(deselect_all)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # Tree widget for files (grouped by notebook)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Name", "Size", "Type"])
        self.tree.setColumnWidth(0, 300)
        self.tree.setColumnWidth(1, 80)
        layout.addWidget(self.tree)

        # Selection count
        self.count_label = QLabel("0 files selected")
        self.count_label.setStyleSheet("color: #666;")
        layout.addWidget(self.count_label)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)

        self.upload_btn = QPushButton("Upload Selected")
        self.upload_btn.setStyleSheet(
            "padding: 10px 20px; font-weight: bold; "
            "background-color: #4285f4; color: white; border-radius: 4px;"
        )
        self.upload_btn.clicked.connect(self.accept)

        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(self.upload_btn)
        layout.addLayout(btn_layout)

    def scan_files(self):
        """Scan output folder for uploadable files."""
        if not self.output_folder.exists():
            return

        # Scan notebook subfolders
        for nb_folder in sorted(self.output_folder.iterdir()):
            if not nb_folder.is_dir():
                continue
            # Skip non-notebook folders
            if nb_folder.name in ('Subtitle_HEBREW', 'Embedded_Videos', 'WhatsApp_Videos', 'Exported'):
                continue

            notebook_name = nb_folder.name
            nb_item = QTreeWidgetItem(self.tree, [notebook_name, "", "Folder"])
            nb_item.setFlags(nb_item.flags() | Qt.ItemFlag.ItemIsAutoTristate | Qt.ItemFlag.ItemIsUserCheckable)
            nb_item.setCheckState(0, Qt.CheckState.Unchecked)
            nb_item.setData(0, Qt.ItemDataRole.UserRole, ("folder", notebook_name))

            # Add files from various subfolders
            subfolders = [
                (nb_folder / "WhatsApp_Videos", "MP4"),
                (nb_folder / "Embedded_Videos", "MKV"),
                (nb_folder / "Subtitle_HEBREW", "SRT"),
                (nb_folder / "Exported", "Export"),
            ]

            for subfolder, file_type in subfolders:
                if subfolder.exists():
                    for f in sorted(subfolder.iterdir()):
                        if f.is_file():
                            size_kb = f.stat().st_size // 1024
                            size_str = f"{size_kb} KB" if size_kb < 1024 else f"{size_kb // 1024} MB"

                            file_item = QTreeWidgetItem(nb_item, [f.name, size_str, file_type])
                            file_item.setFlags(file_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                            file_item.setCheckState(0, Qt.CheckState.Unchecked)
                            file_item.setData(0, Qt.ItemDataRole.UserRole, ("file", str(f), notebook_name))

            nb_item.setExpanded(True)

        self.tree.itemChanged.connect(self._update_count)

    def _set_all_checked(self, checked: bool):
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for i in range(self.tree.topLevelItemCount()):
            self.tree.topLevelItem(i).setCheckState(0, state)
        self._update_count()

    def _update_count(self):
        count = len(self._get_selected_files())
        self.count_label.setText(f"{count} file(s) selected")

    def _get_selected_files(self) -> list:
        """Return list of (file_path, notebook_name) for checked files."""
        files = []
        for i in range(self.tree.topLevelItemCount()):
            nb_item = self.tree.topLevelItem(i)
            for j in range(nb_item.childCount()):
                file_item = nb_item.child(j)
                if file_item.checkState(0) == Qt.CheckState.Checked:
                    data = file_item.data(0, Qt.ItemDataRole.UserRole)
                    if data and data[0] == "file":
                        files.append((data[1], data[2]))  # (path, notebook_name)
        return files

    def get_selected_files(self) -> list:
        return self._get_selected_files()


# ========== MAIN TAB ==========

class PipelineTab(QWidget):
    """Automated pipeline tab - minimal clicks!"""

    def __init__(self):
        super().__init__()
        self.settings = QSettings('HebrewTranscriber', 'Pipeline')

        # State
        self.downloader = None
        self.notebooks = []
        self.output_folder = None

        # Workers
        self.auth_worker = None
        self.list_worker = None
        self.pipeline_worker = None
        self.drive_upload_worker = None

        # Google Drive
        self.drive_uploader = GoogleDriveUploader()

        self.init_ui()
        self.load_settings()

    def init_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # === LEFT: Controls ===
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        left_scroll.setMinimumWidth(480)
        left_scroll.setMaximumWidth(550)

        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setSpacing(12)

        # Title
        title = QLabel("⚡ Automated Pipeline")
        title.setStyleSheet("font-size: 22px; font-weight: bold; color: #4CAF50;")
        left_layout.addWidget(title)

        subtitle = QLabel("2 clicks: Login → START")
        subtitle.setStyleSheet("color: #666; font-size: 13px; margin-bottom: 5px;")
        left_layout.addWidget(subtitle)

        # ===== STEP 0: Output Folder (FIRST!) =====
        folder_group = QGroupBox("📁 Output Folder")
        folder_group.setStyleSheet("QGroupBox { font-weight: bold; font-size: 13px; }")
        folder_layout = QHBoxLayout(folder_group)

        self.output_label = QLabel("Select folder first!")
        self.output_label.setStyleSheet("color: #666;")
        folder_layout.addWidget(self.output_label, 1)

        self.browse_btn = QPushButton("Browse...")
        self.browse_btn.clicked.connect(self.browse_output)
        folder_layout.addWidget(self.browse_btn)

        left_layout.addWidget(folder_group)

        # ===== STEP 1: Login =====
        login_group = QGroupBox("1️⃣ NotebookLM Login")
        login_group.setStyleSheet("QGroupBox { font-weight: bold; font-size: 13px; }")
        login_layout = QVBoxLayout(login_group)

        self.login_btn = QPushButton("🌐 Launch Chrome & Login")
        self.login_btn.setStyleSheet("padding: 12px; font-size: 14px;")
        self.login_btn.clicked.connect(self.on_login)
        login_layout.addWidget(self.login_btn)

        self.login_status = QLabel("")
        login_layout.addWidget(self.login_status)

        left_layout.addWidget(login_group)

        # ===== STEP 2: Select Notebooks =====
        select_group = QGroupBox("2️⃣ Select Notebooks")
        select_group.setStyleSheet("QGroupBox { font-weight: bold; font-size: 13px; }")
        select_layout = QVBoxLayout(select_group)

        # Search box
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search notebooks...")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.setStyleSheet("padding: 6px; font-size: 13px;")
        self.search_box.textChanged.connect(self.on_search)
        select_layout.addWidget(self.search_box)

        btn_row = QHBoxLayout()
        self.select_all_btn = QPushButton("Select All")
        self.select_all_btn.clicked.connect(self.select_all)
        self.deselect_btn = QPushButton("Deselect")
        self.deselect_btn.clicked.connect(self.deselect_all)
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setToolTip("Check for new notebooks (uses cache)")
        self.refresh_btn.clicked.connect(self.on_refresh)
        self.refresh_btn.setEnabled(False)
        self.force_refresh_btn = QPushButton("Full Scan")
        self.force_refresh_btn.setToolTip("Ignore cache, rescan all notebooks")
        self.force_refresh_btn.clicked.connect(self.on_force_refresh)
        self.force_refresh_btn.setEnabled(False)
        self.force_refresh_btn.setStyleSheet("font-size: 11px; padding: 4px 8px;")
        btn_row.addWidget(self.select_all_btn)
        btn_row.addWidget(self.deselect_btn)
        btn_row.addWidget(self.refresh_btn)
        btn_row.addWidget(self.force_refresh_btn)
        select_layout.addLayout(btn_row)

        self.notebook_list = QListWidget()
        self.notebook_list.setMinimumHeight(350)
        self.notebook_list.setStyleSheet("""
            QListWidget {
                font-size: 13px;
                padding: 4px;
            }
            QListWidget::item {
                padding: 6px 4px;
                border-bottom: 1px solid #eee;
            }
        """)
        select_layout.addWidget(self.notebook_list)

        self.notebook_count = QLabel("Login to see notebooks")
        self.notebook_count.setStyleSheet("color: #666;")
        select_layout.addWidget(self.notebook_count)

        left_layout.addWidget(select_group)

        # ===== OPTIONS =====
        options_group = QGroupBox("⚙️ Options")
        options_group.setStyleSheet("QGroupBox { font-weight: bold; font-size: 13px; }")
        options_layout = QVBoxLayout(options_group)

        self.download_cb = QCheckBox("Download videos")
        self.download_cb.setChecked(True)
        options_layout.addWidget(self.download_cb)

        self.transcribe_cb = QCheckBox("Transcribe to Hebrew SRT")
        self.transcribe_cb.setChecked(True)
        options_layout.addWidget(self.transcribe_cb)

        self.embed_cb = QCheckBox("RTL Fix + Embed subtitles")
        self.embed_cb.setChecked(True)
        if not is_mkvmerge_available():
            self.embed_cb.setChecked(False)
            self.embed_cb.setEnabled(False)
            self.embed_cb.setText("RTL Fix + Embed (MKVToolNix not found)")
        options_layout.addWidget(self.embed_cb)

        self.export_md_cb = QCheckBox("Export SRT → Markdown (per-file + merged)")
        self.export_md_cb.setChecked(False)
        options_layout.addWidget(self.export_md_cb)

        self.export_pdf_cb = QCheckBox("Export SRT → PDF (per-file + merged)")
        self.export_pdf_cb.setChecked(False)
        options_layout.addWidget(self.export_pdf_cb)

        self.convert_mp4_cb = QCheckBox("Convert to MP4 (WhatsApp-ready, hard-burned subs)")
        self.convert_mp4_cb.setChecked(False)
        if not is_ffmpeg_available():
            self.convert_mp4_cb.setEnabled(False)
            self.convert_mp4_cb.setText("Convert to MP4 (FFmpeg not found)")
        options_layout.addWidget(self.convert_mp4_cb)

        left_layout.addWidget(options_group)

        # ===== START BUTTON =====
        self.start_btn = QPushButton("▶️  START PIPELINE")
        self.start_btn.setStyleSheet("""
            QPushButton {
                padding: 18px;
                font-size: 18px;
                font-weight: bold;
                background-color: #4CAF50;
                color: white;
                border-radius: 10px;
            }
            QPushButton:hover { background-color: #45a049; }
            QPushButton:disabled { background-color: #cccccc; color: #666; }
        """)
        self.start_btn.clicked.connect(self.on_start_pipeline)
        self.start_btn.setEnabled(False)
        left_layout.addWidget(self.start_btn)

        # Cancel
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.on_cancel)
        self.cancel_btn.setEnabled(False)
        left_layout.addWidget(self.cancel_btn)

        # Standalone merge button
        self.merge_btn = QPushButton("📄 Merge All SRTs to MD/PDF")
        self.merge_btn.setStyleSheet("padding: 10px; font-size: 13px;")
        self.merge_btn.setToolTip("Browse a folder and merge all SRT files found (recursive) into one document")
        self.merge_btn.clicked.connect(self.on_merge_srts)
        left_layout.addWidget(self.merge_btn)

        # ===== GOOGLE DRIVE SECTION =====
        drive_group = QGroupBox("☁️ Google Drive")
        drive_group.setStyleSheet("QGroupBox { font-weight: bold; font-size: 13px; }")
        drive_layout = QVBoxLayout(drive_group)

        # Check if API is available
        if not is_google_api_available():
            no_api_label = QLabel("Google API packages not installed.\nRun: pip install google-auth google-auth-oauthlib google-api-python-client")
            no_api_label.setStyleSheet("color: #c62828; font-size: 11px;")
            no_api_label.setWordWrap(True)
            drive_layout.addWidget(no_api_label)
        else:
            # Auth status
            self.drive_status = QLabel("Not connected")
            self.drive_status.setStyleSheet("color: #666;")
            drive_layout.addWidget(self.drive_status)

            # Auth button row
            drive_btn_row = QHBoxLayout()
            self.drive_auth_btn = QPushButton("🔐 Connect to Google Drive")
            self.drive_auth_btn.setStyleSheet("padding: 8px;")
            self.drive_auth_btn.clicked.connect(self.on_drive_auth)
            drive_btn_row.addWidget(self.drive_auth_btn)

            self.drive_logout_btn = QPushButton("Logout")
            self.drive_logout_btn.setStyleSheet("padding: 8px;")
            self.drive_logout_btn.clicked.connect(self.on_drive_logout)
            self.drive_logout_btn.setVisible(False)
            drive_btn_row.addWidget(self.drive_logout_btn)
            drive_layout.addLayout(drive_btn_row)

            # Upload button
            self.drive_upload_btn = QPushButton("📤 Upload to Drive...")
            self.drive_upload_btn.setStyleSheet("padding: 10px; font-size: 13px;")
            self.drive_upload_btn.setToolTip("Select and upload files to Google Drive")
            self.drive_upload_btn.clicked.connect(self.on_drive_upload)
            self.drive_upload_btn.setEnabled(False)
            drive_layout.addWidget(self.drive_upload_btn)

            # Setup info link
            setup_link = QLabel('<a href="#" style="color: #4285f4;">How to setup Google Drive</a>')
            setup_link.setStyleSheet("font-size: 11px;")
            setup_link.linkActivated.connect(self.show_drive_setup_help)
            drive_layout.addWidget(setup_link)

        left_layout.addWidget(drive_group)

        # Progress
        progress_group = QGroupBox("Progress")
        progress_layout = QVBoxLayout(progress_group)

        self.stage_label = QLabel("Ready")
        self.stage_label.setStyleSheet("font-size: 13px;")
        progress_layout.addWidget(self.stage_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimumHeight(25)
        progress_layout.addWidget(self.progress_bar)

        left_layout.addWidget(progress_group)

        left_layout.addStretch()
        left_scroll.setWidget(left_widget)

        # === RIGHT: Log ===
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)

        log_title = QLabel("Pipeline Log")
        log_title.setStyleSheet("font-size: 14px; font-weight: bold;")
        right_layout.addWidget(log_title)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("font-family: Consolas; font-size: 11px;")
        right_layout.addWidget(self.log_text)

        splitter.addWidget(left_scroll)
        splitter.addWidget(right_widget)
        splitter.setSizes([480, 520])

        main_layout.addWidget(splitter)

    def load_settings(self):
        self.output_folder = self.settings.value('output_folder', '')
        if self.output_folder:
            self.output_label.setText(self.output_folder)
            self.output_label.setStyleSheet("color: #333;")

        # Check for existing Drive auth (only if API is available)
        if is_google_api_available() and self.drive_uploader.is_authenticated():
            self.drive_status.setText("✓ Connected to Google Drive")
            self.drive_status.setStyleSheet("color: green; font-weight: bold;")
            self.drive_upload_btn.setEnabled(True)
            self.drive_logout_btn.setVisible(True)
            self.drive_auth_btn.setText("Reconnect")

    def save_settings(self):
        if self.output_folder:
            self.settings.setValue('output_folder', self.output_folder)

    def log(self, msg: str):
        self.log_text.append(msg)
        self.log_text.verticalScrollBar().setValue(
            self.log_text.verticalScrollBar().maximum()
        )

    def browse_output(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if folder:
            self.output_folder = folder
            self.output_label.setText(folder)
            self.output_label.setStyleSheet("color: #333;")
            self.save_settings()
            self.update_start_button()

    def update_start_button(self):
        """Enable START only when we have: output folder + logged in + notebooks selected"""
        has_folder = bool(self.output_folder)
        has_login = self.downloader is not None
        has_selection = any(
            self.notebook_list.item(i).checkState() == Qt.CheckState.Checked
            for i in range(self.notebook_list.count())
        ) if self.notebook_list.count() > 0 else False

        self.start_btn.setEnabled(has_folder and has_login and has_selection)

    # ========== LOGIN ==========
    def on_login(self):
        self.login_btn.setEnabled(False)
        self.login_status.setText("Starting Chrome...")
        self.log_text.clear()
        self.log("🌐 Launching Chrome for NotebookLM login...")

        self.auth_worker = AuthWorker()
        self.auth_worker.status_update.connect(self.log)
        self.auth_worker.auth_complete.connect(self.on_auth_complete)
        self.auth_worker.start()

    def on_auth_complete(self, success: bool, downloader):
        self.login_btn.setEnabled(True)
        if success:
            self.downloader = downloader
            self.login_status.setText("✓ Connected!")
            self.login_status.setStyleSheet("color: green; font-weight: bold;")
            self.refresh_btn.setEnabled(True)
            self.force_refresh_btn.setEnabled(True)
            self.log("✓ Login successful!")
            self.list_notebooks()
        else:
            self.login_status.setText("✗ Failed")
            self.login_status.setStyleSheet("color: red;")
            self.log("✗ Login failed")

    # ========== LIST NOTEBOOKS ==========
    def list_notebooks(self, force_refresh=False):
        if not self.downloader:
            return

        self.refresh_btn.setEnabled(False)
        self.force_refresh_btn.setEnabled(False)
        self.notebook_list.clear()
        self.notebook_count.setText("Loading...")

        self.list_worker = ListNotebooksWorker(self.downloader, force_refresh)
        self.list_worker.status_update.connect(self.log)
        self.list_worker.list_complete.connect(self.on_list_complete)
        self.list_worker.start()

    def on_list_complete(self, notebooks, new_count):
        notebooks.sort(key=lambda nb: nb.title.lower())
        self.notebooks = notebooks
        self.notebook_list.clear()
        self.refresh_btn.setEnabled(True)
        self.force_refresh_btn.setEnabled(True)

        for nb in notebooks:
            item = QListWidgetItem(f"{nb.emoji} {nb.title}")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, nb)
            self.notebook_list.addItem(item)

        # Show count with new notebooks info
        status_msg = f"{len(notebooks)} notebooks"
        if new_count > 0:
            status_msg += f" ({new_count} new)"
        self.notebook_count.setText(status_msg)
        self.log(f"📓 Found {len(notebooks)} notebooks ({new_count} new)")

        # Connect selection change to update start button
        self.notebook_list.itemChanged.connect(self.update_start_button)
        self.update_start_button()

    def on_search(self, text: str):
        """Filter notebook list by search text."""
        search = text.strip().lower()
        for i in range(self.notebook_list.count()):
            item = self.notebook_list.item(i)
            item.setHidden(search != '' and search not in item.text().lower())

    def select_all(self):
        for i in range(self.notebook_list.count()):
            item = self.notebook_list.item(i)
            if not item.isHidden():
                item.setCheckState(Qt.CheckState.Checked)
        self.update_start_button()

    def deselect_all(self):
        for i in range(self.notebook_list.count()):
            item = self.notebook_list.item(i)
            if not item.isHidden():
                item.setCheckState(Qt.CheckState.Unchecked)
        self.update_start_button()

    def on_refresh(self):
        """Refresh with cache - only find new notebooks."""
        self.search_box.clear()
        self.list_notebooks(force_refresh=False)

    def on_force_refresh(self):
        """Force full rescan - ignore cache."""
        self.search_box.clear()
        self.list_notebooks(force_refresh=True)

    # ========== START PIPELINE ==========
    def on_start_pipeline(self):
        # Get selected notebooks
        selected = []
        for i in range(self.notebook_list.count()):
            item = self.notebook_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                selected.append(item.data(Qt.ItemDataRole.UserRole))

        if not selected:
            QMessageBox.warning(self, "Error", "Please select at least one notebook")
            return

        if not self.output_folder:
            QMessageBox.warning(self, "Error", "Please select output folder")
            return

        # Disable UI
        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.login_btn.setEnabled(False)
        self.browse_btn.setEnabled(False)
        self.progress_bar.setValue(0)

        self.log("\n" + "🚀" * 20)
        self.log("STARTING AUTOMATED PIPELINE")
        self.log("🚀" * 20)
        self.log(f"Notebooks: {len(selected)}")
        self.log(f"Output: {self.output_folder}")

        # Start pipeline worker
        self.pipeline_worker = FullPipelineWorker(
            downloader=self.downloader,
            notebooks=selected,
            output_folder=self.output_folder,
            do_download=self.download_cb.isChecked(),
            do_transcribe=self.transcribe_cb.isChecked(),
            do_embed=self.embed_cb.isChecked(),
            do_export_md=self.export_md_cb.isChecked(),
            do_export_pdf=self.export_pdf_cb.isChecked(),
            do_convert_mp4=self.convert_mp4_cb.isChecked()
        )
        self.pipeline_worker.log_update.connect(self.log)
        self.pipeline_worker.stage_update.connect(self.on_stage_update)
        self.pipeline_worker.pipeline_complete.connect(self.on_pipeline_complete)
        self.pipeline_worker.start()

    def on_stage_update(self, stage: str, progress: int):
        self.stage_label.setText(stage)
        self.progress_bar.setValue(progress)

    def on_pipeline_complete(self, results: dict):
        # Re-enable UI
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.login_btn.setEnabled(True)
        self.browse_btn.setEnabled(True)
        self.stage_label.setText("Complete!")
        self.progress_bar.setValue(100)

        embedded = results.get('embedded', 0)
        transcribed = results.get('transcribed', 0)
        downloaded = results.get('downloaded', 0)
        exported = results.get('exported', 0)
        converted_mp4 = results.get('converted_mp4', 0)

        # Show completion message
        msg = f"Pipeline Complete!\n\n"
        msg += f"Downloaded: {downloaded}\n"
        msg += f"Transcribed: {transcribed}\n"
        msg += f"Exported: {exported}\n"
        msg += f"Embedded: {embedded}"
        if converted_mp4 > 0:
            msg += f"\nMP4 (WhatsApp): {converted_mp4}"

        QMessageBox.information(self, "Complete", msg)

        # Open output folder — prefer WhatsApp folder if MP4 conversion was done
        if converted_mp4 > 0:
            # Open first notebook's WhatsApp folder
            nb_folders = [
                f for f in Path(self.output_folder).iterdir()
                if f.is_dir() and (f / "WhatsApp_Videos").exists()
            ]
            if nb_folders:
                os.startfile(str(nb_folders[0] / "WhatsApp_Videos"))
            elif self.output_folder:
                os.startfile(str(self.output_folder))
        elif embedded > 0:
            embed_folder = Path(self.output_folder) / "Embedded_Videos"
            if embed_folder.exists():
                os.startfile(str(embed_folder))
        elif self.output_folder:
            os.startfile(str(self.output_folder))

    def on_cancel(self):
        if self.pipeline_worker:
            self.pipeline_worker.cancel()
        self.cancel_btn.setEnabled(False)
        self.log("\n⚠️ Cancelling pipeline...")

    def on_merge_srts(self):
        """Standalone merge: select multiple folders, find all SRTs, merge into one file."""
        dialog = MergeSRTDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        folders, output_folder, merge_title, do_md, do_pdf = dialog.get_result()

        if not folders:
            return
        if not output_folder:
            QMessageBox.warning(self, "Error", "No output folder selected")
            return
        if not do_md and not do_pdf:
            QMessageBox.warning(self, "Error", "Select at least one format (MD or PDF)")
            return

        srt_files = find_all_srts_multi(folders)

        if not srt_files:
            QMessageBox.warning(self, "No SRTs", "No .srt files found in selected folders")
            return

        self.log(f"\n📄 Found {len(srt_files)} SRT files across {len(folders)} folders")

        errors = []
        created = []

        if do_md:
            try:
                md_path = output_folder / f"{merge_title}_MERGED.md"
                merge_srts_to_md(srt_files, md_path, merge_title)
                self.log(f"  ✓ MD: {md_path.name}")
                created.append(md_path.name)
            except Exception as e:
                errors.append(f"MD: {e}")
                self.log(f"  ✗ MD error: {e}")

        if do_pdf:
            try:
                pdf_path = output_folder / f"{merge_title}_MERGED.pdf"
                merge_srts_to_pdf(srt_files, pdf_path, merge_title)
                self.log(f"  ✓ PDF: {pdf_path.name}")
                created.append(pdf_path.name)
            except Exception as e:
                errors.append(f"PDF: {e}")
                self.log(f"  ✗ PDF error: {e}")

        if errors:
            QMessageBox.warning(self, "Merge Errors", "\n".join(errors))
        else:
            QMessageBox.information(
                self, "Merge Complete",
                f"Merged {len(srt_files)} SRT files into:\n" +
                "\n".join(f"• {f}" for f in created)
            )
            os.startfile(str(output_folder))

    # ========== GOOGLE DRIVE METHODS ==========

    def on_drive_auth(self):
        """Authenticate with Google Drive."""
        if not self.drive_uploader.is_client_secrets_configured():
            self.show_drive_setup_help()
            return

        self.drive_auth_btn.setEnabled(False)
        self.drive_status.setText("Authenticating...")
        self.log("🔐 Starting Google Drive authentication...")

        # Run auth in main thread (opens browser)
        success = self.drive_uploader.authenticate(self.log)

        if success:
            self.drive_status.setText("✓ Connected to Google Drive")
            self.drive_status.setStyleSheet("color: green; font-weight: bold;")
            self.drive_upload_btn.setEnabled(True)
            self.drive_logout_btn.setVisible(True)
            self.drive_auth_btn.setText("Reconnect")
        else:
            self.drive_status.setText("✗ Authentication failed")
            self.drive_status.setStyleSheet("color: red;")

        self.drive_auth_btn.setEnabled(True)

    def on_drive_logout(self):
        """Logout from Google Drive."""
        self.drive_uploader.logout()
        self.drive_status.setText("Not connected")
        self.drive_status.setStyleSheet("color: #666;")
        self.drive_upload_btn.setEnabled(False)
        self.drive_logout_btn.setVisible(False)
        self.drive_auth_btn.setText("🔐 Connect to Google Drive")
        self.log("Disconnected from Google Drive")

    def on_drive_upload(self):
        """Open file selection dialog and upload to Drive."""
        if not self.output_folder:
            QMessageBox.warning(self, "Error", "No output folder selected")
            return

        if not self.drive_uploader.is_authenticated():
            QMessageBox.warning(self, "Error", "Please connect to Google Drive first")
            return

        dialog = DriveUploadDialog(Path(self.output_folder), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        files = dialog.get_selected_files()
        if not files:
            return

        self.log(f"\n☁️ Uploading {len(files)} files to Google Drive...")
        self.drive_upload_btn.setEnabled(False)
        self.stage_label.setText("Uploading to Drive...")
        self.progress_bar.setValue(0)

        self.drive_upload_worker = DriveUploadWorker(self.drive_uploader, files)
        self.drive_upload_worker.status_update.connect(self.log)
        self.drive_upload_worker.progress_update.connect(self.on_drive_progress)
        self.drive_upload_worker.upload_complete.connect(self.on_drive_upload_complete)
        self.drive_upload_worker.start()

    def on_drive_progress(self, current: int, total: int, filename: str, percent: int):
        """Update progress during Drive upload."""
        self.stage_label.setText(f"Uploading {current}/{total}: {filename}")
        overall = int(((current - 1) / total + (percent / 100) / total) * 100)
        self.progress_bar.setValue(overall)

    def on_drive_upload_complete(self, results: dict):
        """Handle Drive upload completion."""
        self.drive_upload_btn.setEnabled(True)
        self.stage_label.setText("Upload complete!")
        self.progress_bar.setValue(100)

        uploaded = len(results.get("uploaded", []))
        failed = results.get("failed", [])

        self.log(f"✓ Uploaded {uploaded} files to Google Drive")

        if failed:
            self.log(f"✗ Failed: {len(failed)} files")
            for path, error in failed:
                self.log(f"  - {Path(path).name}: {error}")

        msg = f"Uploaded {uploaded} file(s) to Google Drive"
        if failed:
            msg += f"\n\nFailed: {len(failed)} file(s)"

        QMessageBox.information(self, "Upload Complete", msg)

    def show_drive_setup_help(self):
        """Show instructions for setting up Google Drive API."""
        help_text = f"""To enable Google Drive upload:

1. Go to https://console.cloud.google.com/
2. Create a new project (or select existing)
3. Enable the Google Drive API
4. Go to "Credentials" -> "Create Credentials" -> "OAuth client ID"
5. Select "Desktop app" as application type
6. Download the JSON file
7. Rename it to 'client_secrets.json'
8. Place it at:
   {self.drive_uploader.get_client_secrets_path()}

After setup, click "Connect to Google Drive" again."""

        QMessageBox.information(self, "Google Drive Setup", help_text)
