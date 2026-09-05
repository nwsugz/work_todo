"""보드 화면. TODO / TBD 두 칸, 드래그로 옮기면 그 자리에 고정됩니다."""

from __future__ import annotations

import sys
from datetime import date

from PySide6.QtCore import QDate, QPoint, QPointF, QRect, QSignalBlocker, QSize, Qt, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QDrag,
    QFont,
    QFontMetrics,
    QKeySequence,
    QPainter,
    QPen,
    QPixmap,
    QTextCharFormat,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from . import storage
from .models import COLUMNS, TBD, TODO, Task
from .rules import apply_rules, classify

CANVAS = "#1C1F26"
SURFACE = "#262A33"
BORDER = "#343A45"
TEXT = "#E6E8EC"
MUTED = "#98A0AB"
AMBER = "#E2B341"
SLATE = "#7C8593"
PIN = "#7FB2E5"
DONE_GREEN = "#3FBF6F"
URGENT_OVERDUE = "#E2574C"
URGENT_OVERDUE_BG = "#3B2229"
URGENT_SOON = "#E2954A"
URGENT_SOON_BG = "#3A2C1E"
URGENT_DAYS = 3  # 마감일까지 이 안이면 '임박'으로 표시

ROLE_TASK_ID = Qt.ItemDataRole.UserRole
ROLE_CARD = Qt.ItemDataRole.UserRole + 1

COLUMN_LABEL = {TODO: "TODO", TBD: "TBD"}
COLUMN_ACCENT = {TODO: AMBER, TBD: SLATE}

TBD_COLLAPSE_BUTTON_WIDTH = 22
BOARD_SPACING = 14         # TODO/TBD 두 칸 사이 간격(펼쳐졌을 때)
OUTER_RIGHT_MARGIN = 16    # 창 오른쪽 여백(펼쳐졌을 때)

CHECK_SIZE = 16
CHEVRON_SIZE = 13
GUTTER = 24        # 체크박스 시작 위치(항상 이만큼 왼쪽 여백을 둬서, 화살표가 없는 카드도 정렬이 맞습니다)
INDENT_STEP = 22   # 하위 업무 카드를 오른쪽으로 밀어 넣는 폭
CARD_MIN_HEIGHT = 62
CARD_TOP_PAD = 10
CARD_BOTTOM_PAD = 10
TITLE_META_GAP = 4
TITLE_FONT_SIZE = 10
META_FONT_SIZE = 8
WRAP_FLAGS = Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop


def chevron_rect(card_rect: QRect) -> QRect:
    """카드의(패딩·들여쓰기 적용된) 사각형을 받아 접기/펼치기 화살표 위치를 돌려줍니다.
    카드가 여러 줄로 늘어나도 항상 제목 첫 줄 높이에 맞춥니다."""
    return QRect(card_rect.left() + 4, card_rect.top() + 9, CHEVRON_SIZE, CHEVRON_SIZE)


def checkbox_rect(card_rect: QRect) -> QRect:
    """카드의(패딩·들여쓰기 적용된) 사각형을 받아 체크박스 위치를 돌려줍니다.
    카드가 여러 줄로 늘어나도 항상 제목 첫 줄 높이에 맞춥니다."""
    return QRect(card_rect.left() + GUTTER, card_rect.top() + 9, CHECK_SIZE, CHECK_SIZE)


def card_text_area(card_rect: QRect) -> tuple[int, int]:
    """(글자 시작 x, 사용 가능한 폭) 튜플. 카드를 그릴 때와 높이를 잴 때 같은 계산을 씁니다."""
    box = checkbox_rect(card_rect)
    text_left = box.right() + 10
    text_width = max(card_rect.right() - text_left - 6, 20)
    return text_left, text_width


def card_content_rect(option_rect: QRect, card: dict) -> QRect:
    """option.rect(패딩 전 원본)에서 paint()/sizeHint()가 공통으로 쓰는, 패딩·들여쓰기가 적용된 사각형."""
    rect = option_rect.adjusted(4, 3, -4, -3)
    if card.get("indent"):
        rect = rect.adjusted(INDENT_STEP, 0, 0, 0)
    return rect


def ui_font(size: int = 10, bold: bool = False) -> QFont:
    font = QFont("Malgun Gothic" if sys.platform == "win32" else "Noto Sans CJK KR", size)
    font.setBold(bold)
    return font


def due_caption(task: Task, today: date | None = None) -> str:
    if not task.due:
        return "마감일 없음"
    today = today or date.today()
    try:
        due = date.fromisoformat(task.due)
    except ValueError:
        return "마감일 없음"
    days = (due - today).days
    if days < 0:
        return f"{task.due} · {-days}일 지남"
    if days == 0:
        return f"{task.due} · 오늘"
    return f"{task.due} · {days}일 남음"


def task_urgency(task: Task, today: date | None = None) -> str | None:
    """마감일 기준 긴급도. 완료된 업무나 마감일이 없는 업무는 None."""
    if task.done or not task.due:
        return None
    today = today or date.today()
    try:
        due = date.fromisoformat(task.due)
    except ValueError:
        return None
    days = (due - today).days
    if days < 0:
        return "overdue"
    if days <= URGENT_DAYS:
        return "soon"
    return None


def app_stylesheet() -> str:
    """앱 전체(QApplication)에 적용합니다. 창 단위로만 적용하면 달력 팝업처럼 별도 창으로
    뜨는 위젯에는 전달되지 않아서, 반드시 QApplication 레벨에서 걸어야 합니다."""
    return f"""
    QMainWindow, QWidget {{ background: {CANVAS}; color: {TEXT}; }}
    QLabel {{ color: {TEXT}; }}
    QLabel#count {{ color: {MUTED}; font-size: 12px; }}
    QPushButton {{
        background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 5px;
        padding: 6px 12px; color: {TEXT};
    }}
    QPushButton:hover {{ background: #2F3541; }}
    QPushButton:checked {{ border-color: {PIN}; color: {PIN}; }}
    QPushButton#primary {{ background: {AMBER}; border-color: {AMBER}; color: #1C1F26; font-weight: bold; }}
    QPushButton#primary:hover {{ background: #EFC456; }}
    QPushButton#collapseToggle {{ padding: 2px; }}
    QListWidget {{
        background: #1F232B; border: 1px solid {BORDER}; border-radius: 8px; padding: 4px;
    }}
    QListWidget::item {{ border: none; }}
    QLineEdit, QPlainTextEdit, QDateEdit {{
        background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 4px;
        padding: 5px; color: {TEXT};
    }}
    QDialog {{ background: {CANVAS}; }}
    QCalendarWidget QWidget {{ background: {SURFACE}; color: {TEXT}; }}
    QCalendarWidget QToolButton {{ background: {SURFACE}; color: {TEXT}; icon-size: 16px; }}
    QCalendarWidget QMenu {{ background: {SURFACE}; color: {TEXT}; }}
    QCalendarWidget QSpinBox {{ background: {SURFACE}; color: {TEXT}; }}
    QCalendarWidget QAbstractItemView {{
        background: {SURFACE}; color: {TEXT}; outline: none;
        selection-background-color: {AMBER}; selection-color: #1C1F26;
    }}
    QCalendarWidget QAbstractItemView:disabled {{ color: {MUTED}; }}
    QCalendarWidget QHeaderView::section {{
        background: {SURFACE}; color: {TEXT}; border: none; padding: 4px;
    }}
    """


class CardDelegate(QStyledItemDelegate):
    """제목 한 줄, 그 아래 상태 한 줄. 고정된 업무는 왼쪽에 파란 막대가 붙습니다."""

    def sizeHint(self, option, index) -> QSize:
        card = index.data(ROLE_CARD) or {}
        rect = card_content_rect(option.rect, card)
        _text_left, text_width = card_text_area(rect)

        title_metrics = QFontMetrics(ui_font(TITLE_FONT_SIZE, bold=True))
        title_h = title_metrics.boundingRect(QRect(0, 0, text_width, 4000), WRAP_FLAGS, card.get("title", "")).height()
        meta_metrics = QFontMetrics(ui_font(META_FONT_SIZE))
        meta_h = meta_metrics.boundingRect(QRect(0, 0, text_width, 4000), WRAP_FLAGS, card.get("meta", "")).height()

        content_h = CARD_TOP_PAD + title_h + TITLE_META_GAP + meta_h + CARD_BOTTOM_PAD
        # 바깥쪽에 남겨둔 4+3/-4-3 여백(paint에서 rect를 깎아내는 만큼)을 다시 더해 줍니다.
        return QSize(option.rect.width(), max(CARD_MIN_HEIGHT, content_h) + 6)

    def paint(self, painter: QPainter, option, index) -> None:
        card = index.data(ROLE_CARD) or {}
        rect = card_content_rect(option.rect, card)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        urgency = card.get("urgency")
        if urgency == "overdue":
            background, border_color, border_width = QColor(URGENT_OVERDUE_BG), QColor(URGENT_OVERDUE), 1.6
        elif urgency == "soon":
            background, border_color, border_width = QColor(URGENT_SOON_BG), QColor(URGENT_SOON), 1.6
        else:
            background = QColor("#2F3541") if selected else QColor(SURFACE)
            border_color, border_width = QColor(BORDER), 1.0
        if selected and urgency:
            background = background.lighter(115)
        painter.setPen(QPen(border_color, border_width))
        painter.setBrush(background)
        painter.drawRoundedRect(rect, 6, 6)

        if card.get("pinned"):
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(PIN))
            painter.drawRoundedRect(QRect(rect.left() + 1, rect.top() + 8, 3, rect.height() - 16), 2, 2)

        if card.get("has_children"):
            painter.setFont(ui_font(9))
            painter.setPen(QColor(MUTED))
            glyph = "▾" if not card.get("collapsed") else "▸"
            painter.drawText(chevron_rect(rect), Qt.AlignmentFlag.AlignCenter, glyph)

        box = checkbox_rect(rect)
        checked = bool(card.get("checked")) or bool(card.get("done"))
        painter.setPen(QPen(QColor(DONE_GREEN if checked else BORDER), 1.4))
        painter.setBrush(QColor(DONE_GREEN) if checked else Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(box, 4, 4)
        if checked:
            mark = QPen(QColor("#12261A"), 2)
            mark.setCapStyle(Qt.PenCapStyle.RoundCap)
            mark.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(mark)
            painter.drawLine(QPointF(box.left() + 3, box.top() + 8.5), QPointF(box.left() + 6.5, box.bottom() - 3))
            painter.drawLine(QPointF(box.left() + 6.5, box.bottom() - 3), QPointF(box.right() - 2.5, box.top() + 3))

        text_left, text_width = card_text_area(rect)

        # 잘라내는(elide) 대신 줄바꿈으로 전체 글자를 다 보여주고, 카드 높이는 sizeHint에서
        # 이미 그만큼 잡아 둡니다. 취소선은 글꼴의 strike-out 속성을 써서 줄바꿈된 모든 줄에
        # 자동으로 그어지게 합니다.
        title_font = ui_font(TITLE_FONT_SIZE, bold=True)
        title_font.setStrikeOut(checked)
        painter.setFont(title_font)
        painter.setPen(QColor(MUTED) if checked else QColor(TEXT))
        title_rect = QRect(text_left, rect.top() + CARD_TOP_PAD, text_width, 4000)
        title_rect = painter.boundingRect(title_rect, WRAP_FLAGS, card.get("title", ""))
        painter.drawText(title_rect, WRAP_FLAGS, card.get("title", ""))

        painter.setFont(ui_font(META_FONT_SIZE))
        painter.setPen(QColor(MUTED))
        meta_rect = QRect(text_left, title_rect.bottom() + TITLE_META_GAP, text_width, 4000)
        painter.drawText(meta_rect, WRAP_FLAGS, card.get("meta", ""))
        painter.restore()


class ColumnList(QListWidget):
    """드롭을 직접 처리합니다. 목록은 컨트롤러가 다시 그립니다."""

    taskDropped = Signal(str, str, int, bool)  # 업무 id, 대상 칸, 위치, 칸이 바뀌었는지
    taskCheckToggled = Signal(str)  # 업무 id — 체크 표시만 바꿈 (자리 유지)
    taskCompleteRequested = Signal(str)  # 업무 id — 완료 처리(칸 아래로/숨김)
    taskCollapseToggled = Signal(str)  # 업무 id — 하위 업무 접기/펼치기
    taskNestRequested = Signal(str, str)  # 업무 id, 대상 업무 id — 카드 위에 떨어뜨려 하위로 넣기

    def __init__(self, column: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.column = column
        self.setItemDelegate(CardDelegate(self))
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.setSpacing(0)
        self.setUniformItemSizes(False)  # 카드가 줄바꿈으로 세로 길이가 달라질 수 있습니다
        self.setResizeMode(QListWidget.ResizeMode.Adjust)  # 창 크기가 바뀔 때마다 줄바꿈 폭을 다시 계산합니다
        self.setMouseTracking(True)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # 줄바꿈 폭이 창 너비에 따라 달라지는데, Qt는 리사이즈만으로 각 카드의 sizeHint를
        # 다시 계산해 주지 않습니다(항목 크기를 한 번 계산하면 그대로 캐시해 둡니다).
        # 항목을 통째로 다시 만들어야만 새 너비에 맞춰 줄바꿈 높이가 다시 계산됩니다.
        self._rebuild_items()

    def _rebuild_items(self) -> None:
        current_id = self.currentItem().data(ROLE_TASK_ID) if self.currentItem() else None
        snapshot = [
            (self.item(i).data(ROLE_TASK_ID), self.item(i).data(ROLE_CARD))
            for i in range(self.count())
        ]
        self.clear()
        for task_id, card in snapshot:
            item = QListWidgetItem()
            item.setData(ROLE_TASK_ID, task_id)
            item.setData(ROLE_CARD, card)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsDragEnabled)
            self.addItem(item)
            if task_id == current_id:
                self.setCurrentItem(item)

    def _hit(self, pos):
        index = self.indexAt(pos)
        if not index.isValid():
            return None
        item = self.itemFromIndex(index)
        card = item.data(ROLE_CARD) or {}
        rect = self.visualItemRect(item).adjusted(4, 3, -4, -3)
        if card.get("indent"):
            rect = rect.adjusted(INDENT_STEP, 0, 0, 0)
        return item, card, rect

    def _item_at_checkbox(self, pos) -> QListWidgetItem | None:
        hit = self._hit(pos)
        if hit is None:
            return None
        item, _card, rect = hit
        return item if checkbox_rect(rect).contains(pos) else None

    def _item_at_chevron(self, pos) -> QListWidgetItem | None:
        hit = self._hit(pos)
        if hit is None:
            return None
        item, card, rect = hit
        if not card.get("has_children"):
            return None
        return item if chevron_rect(rect).contains(pos) else None

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            item = self._item_at_chevron(pos)
            if item is not None:
                self.taskCollapseToggled.emit(item.data(ROLE_TASK_ID))
                event.accept()
                return
            item = self._item_at_checkbox(pos)
            if item is not None:
                self.taskCheckToggled.emit(item.data(ROLE_TASK_ID))
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        pos = event.position().toPoint()
        hovering = self._item_at_chevron(pos) is not None or self._item_at_checkbox(pos) is not None
        self.setCursor(Qt.CursorShape.PointingHandCursor if hovering else Qt.CursorShape.ArrowCursor)
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            # 오른쪽 버튼으로 누르고 살짝 움직였을 때 드래그로 오인하지 않게 막습니다.
            return
        super().mouseMoveEvent(event)

    def startDrag(self, supportedActions) -> None:
        if QApplication.mouseButtons() != Qt.MouseButton.LeftButton:
            return
        item = self.currentItem()
        if item is None:
            return
        index = self.indexFromItem(item)
        rect = self.visualItemRect(item)

        # 기본 드래그 미리보기 대신, 카드 그대로를 정확한 크기로 직접 그려서 씁니다.
        # (기본 방식은 카드가 실제 크기보다 크게 잡혀 드래그 중 다른 카드와 겹쳐 보이는 문제가 있었습니다.)
        pixmap = QPixmap(rect.size())
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        option = QStyleOptionViewItem()
        self.initViewItemOption(option)
        option.rect = QRect(0, 0, rect.width(), rect.height())
        self.itemDelegate().paint(painter, option, index)
        painter.end()

        drag = QDrag(self)
        drag.setMimeData(self.model().mimeData([index]))
        drag.setPixmap(pixmap)
        drag.setHotSpot(QPoint(16, rect.height() // 2))
        drag.exec(supportedActions, Qt.DropAction.MoveAction)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete):
            item = self.currentItem()
            if item is not None:
                self.taskCompleteRequested.emit(item.data(ROLE_TASK_ID))
                event.accept()
                return
        super().keyPressEvent(event)

    def dragEnterEvent(self, event) -> None:
        if isinstance(event.source(), ColumnList):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        if isinstance(event.source(), ColumnList):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:
        source = event.source()
        if not isinstance(source, ColumnList):
            event.ignore()
            return
        items = source.selectedItems()
        if not items:
            event.ignore()
            return
        item = items[0]
        task_id = item.data(ROLE_TASK_ID)
        pos = event.position().toPoint()
        target_index = self.indexAt(pos)
        indicator = self.dropIndicatorPosition()

        if indicator == QAbstractItemView.DropIndicatorPosition.OnItem and target_index.isValid():
            target_item = self.itemFromIndex(target_index)
            target_id = target_item.data(ROLE_TASK_ID)
            if target_id != task_id:
                event.setDropAction(Qt.DropAction.MoveAction)
                event.accept()
                self.taskNestRequested.emit(task_id, target_id)
                return

        row = target_index.row()
        if row < 0:
            row = self.count()
        elif indicator == QAbstractItemView.DropIndicatorPosition.BelowItem:
            row += 1

        moved_across = source is not self
        if not moved_across:
            current_row = self.row(item)
            if row > current_row:
                row -= 1

        event.setDropAction(Qt.DropAction.MoveAction)
        event.accept()
        self.taskDropped.emit(task_id, self.column, row, moved_across)


class TaskDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None = None,
        task: Task | None = None,
        categories: list[str] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("업무 편집" if task else "새 업무")
        self.setMinimumWidth(400)
        categories = categories or []

        self.title_edit = QLineEdit(task.title if task else "")
        self.title_edit.setPlaceholderText("무엇을 해야 하나요?")

        self.category_combo = QComboBox()
        self.category_combo.addItem("(없음)", None)
        for name in categories:
            self.category_combo.addItem(name, name)
        if task and task.category in categories:
            self.category_combo.setCurrentIndex(categories.index(task.category) + 1)

        self.no_due = QCheckBox("마감일 없음")
        self.due_edit = QDateEdit()
        self.due_edit.setCalendarPopup(True)
        self.due_edit.setDisplayFormat("yyyy-MM-dd")
        # 요일 표시줄(일월화수목금토)은 QCalendarWidget이 스타일시트를 안 타고 직접 그려서,
        # 코드로 형식을 지정해야 어두운 배경에서도 글자가 보입니다.
        calendar = self.due_edit.calendarWidget()
        header_format = QTextCharFormat()
        header_format.setBackground(QColor(SURFACE))
        header_format.setForeground(QColor(TEXT))
        header_format.setFontUnderline(True)  # 요일 글자 아래에 밑줄을 그어 날짜 칸과 구분되게 합니다
        calendar.setHeaderTextFormat(header_format)
        weekend_format = QTextCharFormat()
        weekend_format.setForeground(QColor(TEXT))
        calendar.setWeekdayTextFormat(Qt.DayOfWeek.Saturday, weekend_format)
        calendar.setWeekdayTextFormat(Qt.DayOfWeek.Sunday, weekend_format)
        if task and task.due:
            self.due_edit.setDate(QDate.fromString(task.due, "yyyy-MM-dd"))
        else:
            self.due_edit.setDate(QDate.currentDate())
            self.no_due.setChecked(True)
        # 달력은 항상 눌러서 바로 열립니다. 날짜를 실제로 고르면(직접 편집 포함) '마감일 없음'을 자동으로 해제합니다.
        self.due_edit.dateChanged.connect(lambda _value: self.no_due.setChecked(False))

        due_row = QHBoxLayout()
        due_row.addWidget(self.due_edit, 1)
        due_row.addWidget(self.no_due)

        self.tags_edit = QLineEdit(", ".join(task.tags) if task else "")
        self.tags_edit.setPlaceholderText("쉼표로 구분 (예: 대기, 보고)")

        self.note_edit = QPlainTextEdit(task.note if task else "")
        self.note_edit.setPlaceholderText("메모. 규칙의 단어 조건은 메모도 함께 봅니다.")
        self.note_edit.setFixedHeight(90)

        form = QFormLayout()
        form.addRow("제목", self.title_edit)
        form.addRow("카테고리", self.category_combo)
        form.addRow("마감일", due_row)
        form.addRow("태그", self.tags_edit)
        form.addRow("메모", self.note_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("저장")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def accept(self) -> None:
        if not self.title_edit.text().strip():
            QMessageBox.information(self, "제목이 비었습니다", "제목을 입력해 주세요.")
            self.title_edit.setFocus()
            return
        super().accept()

    def values(self) -> dict:
        tags = [t.strip() for t in self.tags_edit.text().split(",") if t.strip()]
        return {
            "title": self.title_edit.text().strip(),
            "category": self.category_combo.currentData(),
            "due": None if self.no_due.isChecked() else self.due_edit.date().toString("yyyy-MM-dd"),
            "tags": tags,
            "note": self.note_edit.toPlainText().strip(),
        }


class SettingsDialog(QDialog):
    """카테고리 우선순위(위쪽일수록 우선) 설정. 목록을 드래그해서 순서를 바꿉니다."""

    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window)
        self.window = window
        self.setWindowTitle("설정")
        self.setMinimumWidth(360)

        category_label = QLabel("카테고리 우선순위")
        self.category_list = QListWidget()
        self.category_list.addItems(self.window.settings.get("categories", []))
        self.category_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.category_list.model().rowsMoved.connect(lambda *_: self._sync())

        add_button = QPushButton("추가")
        add_button.clicked.connect(self._add_category)
        remove_button = QPushButton("삭제")
        remove_button.clicked.connect(self._remove_category)

        category_buttons = QHBoxLayout()
        category_buttons.addWidget(add_button)
        category_buttons.addWidget(remove_button)
        category_buttons.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addWidget(category_label)
        layout.addWidget(self.category_list)
        layout.addLayout(category_buttons)

    def _category_names(self) -> list[str]:
        return [self.category_list.item(i).text() for i in range(self.category_list.count())]

    def _add_category(self) -> None:
        name, ok = QInputDialog.getText(self, "카테고리 추가", "이름")
        name = name.strip()
        if not ok or not name or name in self._category_names():
            return
        self.category_list.addItem(name)
        self._sync()

    def _remove_category(self) -> None:
        row = self.category_list.currentRow()
        if row >= 0:
            self.category_list.takeItem(row)
            self._sync()

    def _sync(self) -> None:
        self.window.settings["categories"] = self._category_names()
        storage.save_settings(self.window.settings)
        self.window.reapply_rules()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("TODO / TBD 보드")
        self.resize(880, 620)

        self.tasks: list[Task] = storage.load_tasks()
        self.rules, _ = storage.load_rules()
        self.settings: dict = storage.load_settings()
        self.show_done = False

        self.lists: dict[str, ColumnList] = {}
        self.counters: dict[str, QLabel] = {}
        self.column_wrappers: dict[str, QWidget] = {}
        self._tbd_expanded_width = 300  # 접었다 펼 때 되돌아갈 폭. 접기 직전 실제 폭으로 매번 갱신됩니다.

        self._build_ui()
        self._restore_settings()
        apply_rules(self.tasks, self.rules)
        self.render()

    # 화면 구성 -------------------------------------------------------------
    def _build_ui(self) -> None:
        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(16, 14, OUTER_RIGHT_MARGIN, 10)
        outer.setSpacing(12)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        add_button = QPushButton("새 업무")
        add_button.setObjectName("primary")
        add_button.clicked.connect(self.add_task)
        self.done_toggle = QPushButton("완료 항목 보기")
        self.done_toggle.setCheckable(True)
        self.done_toggle.toggled.connect(self.toggle_done)
        settings_button = QPushButton("⚙")
        settings_button.setToolTip("설정")
        settings_button.clicked.connect(self.open_settings)
        self.pin_toggle = QPushButton("📌")
        self.pin_toggle.setCheckable(True)
        self.pin_toggle.setToolTip("항상 위 (다른 창을 띄워도 이 창이 뒤로 가지 않습니다. Ctrl+T)")
        self.pin_toggle.toggled.connect(self.toggle_always_on_top)
        toolbar.addWidget(add_button)
        toolbar.addWidget(self.done_toggle)
        toolbar.addStretch(1)
        toolbar.addWidget(settings_button)
        toolbar.addWidget(self.pin_toggle)
        outer.addLayout(toolbar)

        board = QHBoxLayout()
        board.setSpacing(BOARD_SPACING)
        for column in COLUMNS:
            board.addWidget(self._build_column(column), 1)
        outer.addLayout(board, 1)
        self.board = board
        self.outer = outer

        self.setCentralWidget(central)

        new_action = QAction(self)
        new_action.setShortcut(QKeySequence.StandardKey.New)
        new_action.triggered.connect(self.add_task)
        refresh_action = QAction(self)
        refresh_action.setShortcut(QKeySequence("F5"))
        refresh_action.triggered.connect(self.reapply_rules)
        pin_action = QAction(self)
        pin_action.setShortcut(QKeySequence("Ctrl+T"))
        pin_action.triggered.connect(self.pin_toggle.toggle)
        self.addAction(new_action)
        self.addAction(refresh_action)
        self.addAction(pin_action)

    def _restore_settings(self) -> None:
        with QSignalBlocker(self.done_toggle):
            self.done_toggle.setChecked(bool(self.settings.get("show_done", False)))
        self.show_done = self.done_toggle.isChecked()
        self.done_toggle.setText("DONE" if self.show_done else "완료 항목 보기")

        tbd_collapsed = bool(self.settings.get("tbd_collapsed", False))
        with QSignalBlocker(self.collapse_button):
            self.collapse_button.setChecked(tbd_collapsed)
        self.column_wrappers[TBD].setVisible(not tbd_collapsed)
        self.expand_button.setVisible(tbd_collapsed)
        self._apply_collapsed_spacing(tbd_collapsed)

        always_on_top = bool(self.settings.get("always_on_top", False))
        with QSignalBlocker(self.pin_toggle):
            self.pin_toggle.setChecked(always_on_top)
        if always_on_top:
            self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)

        geo = self.settings.get("geometry")
        if isinstance(geo, dict) and all(isinstance(geo.get(k), int) for k in ("x", "y", "w", "h")):
            self.setGeometry(geo["x"], geo["y"], geo["w"], geo["h"])

    def _build_column(self, column: str) -> QWidget:
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        header = QHBoxLayout()
        if column == TBD:
            self.collapse_button = QPushButton("▾")
            self.collapse_button.setObjectName("collapseToggle")
            self.collapse_button.setCheckable(True)
            self.collapse_button.setFixedWidth(TBD_COLLAPSE_BUTTON_WIDTH)
            self.collapse_button.clicked.connect(self.toggle_tbd_collapsed)
            header.addWidget(self.collapse_button)
        name = QLabel(COLUMN_LABEL[column])
        name.setFont(ui_font(12, bold=True))
        name.setStyleSheet(f"color: {COLUMN_ACCENT[column]};")
        count = QLabel("0")
        count.setObjectName("count")
        header.addWidget(name)
        header.addWidget(count)
        header.addStretch(1)
        if column == TODO:
            # TBD를 접으면 그 칸 전체가 사라지므로, 다시 펼치는 버튼은 TODO 쪽 헤더 맨 오른쪽에
            # 둡니다. 같은 헤더 줄이라 TODO 카드의 오른쪽 끝과 정확히 같은 선에 놓입니다.
            self.expand_button = QPushButton("▸")
            self.expand_button.setObjectName("collapseToggle")
            self.expand_button.setFixedWidth(TBD_COLLAPSE_BUTTON_WIDTH)
            self.expand_button.setToolTip("TBD 펼치기")
            self.expand_button.clicked.connect(self.expand_tbd)
            self.expand_button.setVisible(False)
            header.addWidget(self.expand_button)
        layout.addLayout(header)

        listing = ColumnList(column)
        listing.taskDropped.connect(self.on_task_dropped)
        listing.taskCheckToggled.connect(self.on_task_check_toggled)
        listing.taskCompleteRequested.connect(self.on_task_complete_requested)
        listing.taskCollapseToggled.connect(self.on_task_collapse_toggled)
        listing.taskNestRequested.connect(self.on_task_nest_requested)
        listing.customContextMenuRequested.connect(
            lambda pos, c=column: self.show_context_menu(c, pos)
        )
        listing.itemDoubleClicked.connect(self.edit_selected)
        layout.addWidget(listing, 1)

        self.lists[column] = listing
        self.counters[column] = count
        self.column_wrappers[column] = wrapper
        return wrapper

    # 그리기 ----------------------------------------------------------------
    def category_rank(self, task: Task) -> int:
        """설정에서 정한 카테고리 우선순위. 목록 위쪽(인덱스 0)이 가장 높은 우선순위입니다.
        카테고리가 없거나 목록에 없는 값이면 가장 낮은 우선순위로 취급합니다."""
        categories = self.settings.get("categories", [])
        if task.category and task.category in categories:
            return categories.index(task.category)
        return len(categories)

    def has_children(self, task_id: str) -> bool:
        return any(t.parent_id == task_id for t in self.tasks)

    def top_level_tasks(self, column: str) -> list[Task]:
        items = [
            t for t in self.tasks
            if t.column == column and t.parent_id is None and (self.show_done or not t.done)
        ]
        return sorted(items, key=lambda t: (t.done, t.checked, self.category_rank(t), t.order))

    def child_tasks(self, parent_id: str) -> list[Task]:
        items = [t for t in self.tasks if t.parent_id == parent_id and (self.show_done or not t.done)]
        return sorted(items, key=lambda t: (t.done, t.checked, t.order))

    def visible_tasks(self, column: str) -> list[Task]:
        """부모 다음에 그 하위 업무들이 이어지는, 화면에 그릴 순서 그대로의 목록."""
        result: list[Task] = []
        for parent in self.top_level_tasks(column):
            result.append(parent)
            if not parent.collapsed:
                result.extend(self.child_tasks(parent.id))
        return result

    def render(self) -> None:
        for column, listing in self.lists.items():
            selected_id = None
            current = listing.currentItem()
            if current:
                selected_id = current.data(ROLE_TASK_ID)
            listing.clear()
            tasks = self.visible_tasks(column)
            for task in tasks:
                item = QListWidgetItem()
                item.setData(ROLE_TASK_ID, task.id)
                item.setData(ROLE_CARD, self._card(task))
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsDragEnabled)
                listing.addItem(item)
                if task.id == selected_id:
                    listing.setCurrentItem(item)
            pinned = sum(1 for t in tasks if t.pinned)
            label = str(len(tasks)) + (f" · 고정 {pinned}" if pinned else "")
            self.counters[column].setText(label)

    def _card(self, task: Task) -> dict:
        parts = []
        if task.category:
            parts.append(f"[{task.category}]")
        parts.append(due_caption(task))
        if task.tags:
            parts.append(" ".join(f"#{t}" for t in task.tags))
        children = [t for t in self.tasks if t.parent_id == task.id]
        if children:
            done_children = sum(1 for t in children if t.done)
            parts.append(f"하위 {done_children}/{len(children)}")
        return {
            "title": task.title,
            "meta": "  ·  ".join(parts),
            "pinned": task.pinned,
            "checked": task.checked,
            "done": task.done,
            "urgency": task_urgency(task),
            "indent": 1 if task.parent_id else 0,
            "has_children": bool(children),
            "collapsed": task.collapsed,
        }

    # 동작 ------------------------------------------------------------------
    def find(self, task_id: str) -> Task | None:
        return next((t for t in self.tasks if t.id == task_id), None)

    def reorder(self, column: str, task_id: str, row: int) -> None:
        """화면에 보이던 순서(row)에서, 옮긴 업무가 같은 무리(최상위 업무들 혹은 같은 부모의 하위 업무들) 안에서
        정확히 몇 번째로 왔는지를 계산해 그 무리의 order 값을 다시 매깁니다."""
        task = self.find(task_id)
        if task is None:
            return
        flat = [t for t in self.visible_tasks(column) if t.id != task_id]
        row = max(0, min(row, len(flat)))
        if task.parent_id:
            preceding = sum(1 for t in flat[:row] if t.parent_id == task.parent_id)
            siblings = [t.id for t in flat if t.parent_id == task.parent_id]
        else:
            preceding = sum(1 for t in flat[:row] if t.parent_id is None)
            siblings = [t.id for t in flat if t.parent_id is None]
        siblings.insert(preceding, task_id)
        for index, sibling_id in enumerate(siblings):
            sibling = self.find(sibling_id)
            if sibling:
                sibling.order = index

    def on_task_dropped(self, task_id: str, column: str, row: int, moved_across: bool) -> None:
        task = self.find(task_id)
        if task is None:
            return
        if moved_across:
            task.column = column
            task.pinned = True
            task.parent_id = None
        self.reorder(column, task_id, row)
        self.persist()
        self.render()

    def on_task_nest_requested(self, task_id: str, target_id: str) -> None:
        if task_id == target_id:
            return
        task = self.find(task_id)
        target = self.find(target_id)
        if task is None or target is None:
            return
        if target.parent_id is not None:
            return  # 하위 업무 아래에 또 하위 업무를 넣지는 않습니다 (한 단계까지만)
        if self.has_children(task.id):
            return  # 이미 하위 업무를 가진 업무는 다른 업무의 하위로 넣지 않습니다
        task.parent_id = target.id
        task.pinned = True
        task.column = target.column
        siblings = [t for t in self.tasks if t.parent_id == target.id and t.id != task.id]
        task.order = len(siblings)
        target.collapsed = False
        self.persist()
        self.render()

    def on_task_collapse_toggled(self, task_id: str) -> None:
        task = self.find(task_id)
        if task is None:
            return
        task.collapsed = not task.collapsed
        self.persist()
        self.render()

    def add_task(self) -> None:
        dialog = TaskDialog(self, categories=self.settings.get("categories", []))
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        task = Task(**values)
        task.column, task.matched_rule = classify(task, self.rules)
        task.order = len(self.top_level_tasks(task.column))
        self.tasks.append(task)
        self.persist()
        self.render()

    def add_subtask(self, parent: Task) -> None:
        dialog = TaskDialog(self, categories=self.settings.get("categories", []))
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        task = Task(**values)
        task.parent_id = parent.id
        task.pinned = True
        task.column = parent.column
        task.order = len(self.child_tasks(parent.id))
        parent.collapsed = False
        self.tasks.append(task)
        self.persist()
        self.render()

    def current_task(self, column: str) -> Task | None:
        item = self.lists[column].currentItem()
        return self.find(item.data(ROLE_TASK_ID)) if item else None

    def edit_selected(self, item: QListWidgetItem) -> None:
        task = self.find(item.data(ROLE_TASK_ID))
        if task:
            self.edit_task(task)

    def edit_task(self, task: Task) -> None:
        dialog = TaskDialog(self, task, categories=self.settings.get("categories", []))
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        for key, value in dialog.values().items():
            setattr(task, key, value)
        if not task.pinned:
            task.column, task.matched_rule = classify(task, self.rules)
        self.persist()
        self.render()

    def unpin(self, task: Task) -> None:
        task.pinned = False
        task.parent_id = None  # 하위 업무는 항상 고정 상태이므로, 고정을 풀면 상위에서도 떼어냅니다
        task.column, task.matched_rule = classify(task, self.rules)
        self.persist()
        self.render()

    def toggle_done(self, checked: bool) -> None:
        self.show_done = checked
        self.done_toggle.setText("DONE" if checked else "완료 항목 보기")
        self.render()

    def _apply_collapsed_spacing(self, collapsed: bool) -> None:
        """접었을 때는 TODO와 TBD 사이 간격만 없앱니다. 창 오른쪽 여백은 왼쪽과 똑같이
        항상 그대로 둬서(OUTER_RIGHT_MARGIN), 접었을 때도 왼쪽만큼의 여백이 남습니다."""
        self.board.setSpacing(0 if collapsed else BOARD_SPACING)

    def expand_tbd(self) -> None:
        self.collapse_button.setChecked(False)
        self.toggle_tbd_collapsed()

    def toggle_tbd_collapsed(self) -> None:
        """TBD만 접을 수 있습니다. 접으면 그 칸을 통째로 숨겨서(TODO 카드의 오른쪽 끝과 다시
        펼치는 버튼이 같은 선에 놓이도록) 창 자체도 그 칸이 쓰던 폭만큼 줄어들게 합니다."""
        collapsed = self.collapse_button.isChecked()
        wrapper = self.column_wrappers[TBD]
        self.expand_button.setVisible(collapsed)
        self._apply_collapsed_spacing(collapsed)

        if collapsed:
            self._tbd_expanded_width = wrapper.width()
            wrapper.setVisible(False)
            shrink = self._tbd_expanded_width + BOARD_SPACING
        else:
            wrapper.setVisible(True)
            shrink = -(self._tbd_expanded_width + BOARD_SPACING)
        # 위젯을 숨기고/보이는 것만으로는 레이아웃이 바로 다시 계산되지 않아서(다음 이벤트 루프까지
        # 옛 크기를 그대로 들고 있습니다), TODO 칸이 남은 폭을 즉시 넘겨받도록 강제로 재계산시킵니다.
        self.board.activate()
        if shrink > 0:
            self.resize(max(self.minimumWidth(), self.width() - shrink), self.height())
        elif shrink < 0:
            self.resize(self.width() - shrink, self.height())

        self.settings["tbd_collapsed"] = collapsed
        storage.save_settings(self.settings)

    def toggle_always_on_top(self, checked: bool) -> None:
        was_visible = self.isVisible()
        flags = self.windowFlags()
        if checked:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        if was_visible:
            self.show()
        self.settings["always_on_top"] = checked
        storage.save_settings(self.settings)

    def delete_task(self, task: Task) -> None:
        children = [t for t in self.tasks if t.parent_id == task.id]
        message = f"'{task.title}'을(를) 지울까요?"
        if children:
            message += f" 하위 업무 {len(children)}개도 함께 지워집니다."
        answer = QMessageBox.question(self, "삭제", message)
        if answer != QMessageBox.StandardButton.Yes:
            return
        remove_ids = {task.id} | {t.id for t in children}
        self.tasks = [t for t in self.tasks if t.id not in remove_ids]
        self.persist()
        self.render()

    def show_context_menu(self, column: str, pos) -> None:
        task = self.current_task(column)
        listing = self.lists[column]
        item = listing.itemAt(pos)
        if item:
            listing.setCurrentItem(item)
            task = self.find(item.data(ROLE_TASK_ID))
        if task is None:
            return
        menu = QMenu(self)
        menu.addAction("편집", lambda: self.edit_task(task))
        if task.parent_id is None:
            menu.addAction("하위 업무 추가", lambda: self.add_subtask(task))
        menu.addAction("완료 취소" if task.done else "완료 처리", lambda: self.set_done(task, not task.done))
        if task.pinned:
            menu.addAction("고정 풀고 규칙에 맡기기", lambda: self.unpin(task))
        else:
            menu.addAction("이 자리에 고정", lambda: self.pin(task))
        menu.addSeparator()
        menu.addAction("삭제", lambda: self.delete_task(task))
        menu.exec(listing.mapToGlobal(pos))

    def pin(self, task: Task) -> None:
        task.pinned = True
        self.persist()
        self.render()

    def set_done(self, task: Task, done: bool) -> None:
        task.done = done
        self.persist()
        self.render()

    def set_checked(self, task: Task, checked: bool) -> None:
        task.checked = checked
        self.persist()
        self.render()

    def on_task_check_toggled(self, task_id: str) -> None:
        task = self.find(task_id)
        if task is None:
            return
        self.set_checked(task, not task.checked)

    def on_task_complete_requested(self, task_id: str) -> None:
        task = self.find(task_id)
        if task is None or task.done:
            return
        self.set_done(task, True)

    def reapply_rules(self) -> None:
        self.rules, _ = storage.load_rules()
        apply_rules(self.tasks, self.rules)
        self.persist()
        self.render()

    def open_settings(self) -> None:
        dialog = SettingsDialog(self)
        dialog.exec()
        self.render()

    def persist(self) -> None:
        storage.save_tasks(self.tasks)

    def closeEvent(self, event) -> None:
        self.persist()
        geo = self.geometry()
        self.settings.update({
            "show_done": self.show_done,
            "always_on_top": bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint),
            "geometry": {"x": geo.x(), "y": geo.y(), "w": geo.width(), "h": geo.height()},
        })
        storage.save_settings(self.settings)
        super().closeEvent(event)


def run() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("TodoTBD")
    app.setFont(ui_font(10))
    app.setStyleSheet(app_stylesheet())
    window = MainWindow()
    window.show()
    return app.exec()
