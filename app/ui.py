"""보드 화면. TODO / TBD 두 칸, 드래그로 옮기면 그 자리에 고정됩니다."""

from __future__ import annotations

import calendar as calendar_module
import sys
from datetime import date, datetime

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
    QFrame,
    QGridLayout,
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
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import storage
from .models import COLUMNS, TBD, TODO, Task
from .rules import apply_rules, classify

URGENT_DAYS = 3  # 마감일까지 이 안이면 '임박'으로 표시

# 노션풍 라이트/다크 팔레트. CardDelegate 등에서는 아래 이름들을 그냥 모듈 전역 변수처럼
# 씁니다(예: QColor(SURFACE)) — apply_theme()이 이 이름들 자체를 다시 바인딩해서 테마를
# 바꾸면, 이미 정의된 함수들도 다음 호출부터 새 색을 그대로 씁니다(파이썬 전역 조회 특성).
THEMES: dict[str, dict[str, str]] = {
    "dark": {
        "CANVAS": "#191919",
        "SURFACE": "#2B2B2B",
        "SURFACE_HOVER": "#363636",
        "SELECTED_BG": "#3A3A3A",
        "BORDER": "#3D3D3D",
        "TEXT": "#E9E9E7",
        "MUTED": "#9B9A97",
        "AMBER": "#D9A441",
        "SLATE": "#8B8B88",
        "PIN": "#5B9BD9",
        "DONE_GREEN": "#3FA172",
        "URGENT_OVERDUE": "#E0555A",
        "URGENT_OVERDUE_BG": "#3A2426",
        "URGENT_SOON": "#D98A3D",
        "URGENT_SOON_BG": "#332A20",
        "PRIMARY_BG": "#D9A441",
        "PRIMARY_TEXT": "#191919",
    },
    "light": {
        "CANVAS": "#FFFFFF",
        "SURFACE": "#F7F6F3",
        "SURFACE_HOVER": "#EDECE9",
        "SELECTED_BG": "#E3E2DF",
        "BORDER": "#E3E2E0",
        "TEXT": "#37352F",
        "MUTED": "#9B9A97",
        "AMBER": "#C9791A",
        "SLATE": "#6B6B68",
        "PIN": "#2383E2",
        "DONE_GREEN": "#2F9E64",
        "URGENT_OVERDUE": "#E03E3E",
        "URGENT_OVERDUE_BG": "#FBEAEA",
        "URGENT_SOON": "#D9730D",
        "URGENT_SOON_BG": "#FBF0E4",
        "PRIMARY_BG": "#2383E2",
        "PRIMARY_TEXT": "#FFFFFF",
    },
}

CURRENT_THEME = "dark"


def apply_theme(name: str) -> None:
    """색상 전역 변수들을 해당 테마 값으로 다시 바인딩합니다."""
    global CURRENT_THEME
    if name not in THEMES:
        name = "dark"
    CURRENT_THEME = name
    globals().update(THEMES[name])


apply_theme(CURRENT_THEME)

ROLE_TASK_ID = Qt.ItemDataRole.UserRole
ROLE_CARD = Qt.ItemDataRole.UserRole + 1

COLUMN_LABEL = {TODO: "TODO", TBD: "TBD"}


def column_accent(column: str) -> str:
    """COLUMN_ACCENT를 딕셔너리로 미리 만들어두면 테마를 바꿔도 예전 색이 그대로 남기 때문에,
    호출할 때마다 지금 테마의 AMBER/SLATE를 그대로 읽어옵니다."""
    return AMBER if column == TODO else SLATE

TBD_COLLAPSE_BUTTON_WIDTH = 22
BOARD_SPACING = 14         # TODO/TBD 두 칸 사이 간격(펼쳐졌을 때)
OUTER_RIGHT_MARGIN = 16    # 창 오른쪽 여백(펼쳐졌을 때)

CHECK_SIZE = 16
CHEVRON_SIZE = 13
GUTTER = 24        # 체크박스 시작 위치(항상 이만큼 왼쪽 여백을 둬서, 화살표가 없는 카드도 정렬이 맞습니다)
INDENT_STEP = 22   # 하위 업무 카드를 오른쪽으로 밀어 넣는 폭
CARD_MIN_HEIGHT = 50
CARD_TOP_PAD = 10
CARD_BOTTOM_PAD = 8
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


def style_calendar_popup(date_edit: QDateEdit) -> None:
    """요일 표시줄(일월화수목금토)은 QCalendarWidget이 스타일시트를 안 타고 직접 그려서,
    코드로 형식을 지정해야 어두운 배경에서도 글자가 보입니다. 달력 팝업이 있는 QDateEdit마다
    똑같이 적용해야 하므로 한 곳에 모아둡니다."""
    calendar = date_edit.calendarWidget()
    header_format = QTextCharFormat()
    header_format.setBackground(QColor(SURFACE))
    header_format.setForeground(QColor(TEXT))
    header_format.setFontUnderline(True)  # 요일 글자 아래에 밑줄을 그어 날짜 칸과 구분되게 합니다
    calendar.setHeaderTextFormat(header_format)
    weekend_format = QTextCharFormat()
    weekend_format.setForeground(QColor(TEXT))
    calendar.setWeekdayTextFormat(Qt.DayOfWeek.Saturday, weekend_format)
    calendar.setWeekdayTextFormat(Qt.DayOfWeek.Sunday, weekend_format)


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
    QLabel {{ color: {TEXT}; background: transparent; }}
    QLabel#count {{ color: {MUTED}; font-size: 12px; }}
    QPushButton {{
        background: transparent; border: 1px solid transparent; border-radius: 6px;
        padding: 6px 12px; color: {TEXT};
    }}
    QPushButton:hover {{ background: {SURFACE_HOVER}; }}
    QPushButton:checked {{ background: {SURFACE_HOVER}; color: {PIN}; }}
    QPushButton#primary {{ background: {PRIMARY_BG}; color: {PRIMARY_TEXT}; font-weight: 600; }}
    QPushButton#primary:hover {{ background: {PRIMARY_BG}; }}
    QPushButton#collapseToggle {{ padding: 2px; border: none; }}
    QListWidget {{
        background: transparent; border: 1px solid {BORDER}; border-radius: 8px; padding: 4px;
    }}
    QListWidget::item {{ border: none; padding: 4px; }}
    QListWidget::item:selected {{ background: {SELECTED_BG}; color: {TEXT}; }}
    QListWidget::item:selected:!active {{ background: {SELECTED_BG}; color: {TEXT}; }}
    QTreeWidget {{
        background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; color: {TEXT};
    }}
    QTreeWidget::item {{ padding: 4px; }}
    QTreeWidget::item:selected {{ background: {SELECTED_BG}; color: {TEXT}; }}
    QLineEdit, QPlainTextEdit, QDateEdit {{
        background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 6px;
        padding: 6px 8px; color: {TEXT};
    }}
    QDialog {{ background: {CANVAS}; }}
    QCalendarWidget QWidget {{ background: {SURFACE}; color: {TEXT}; }}
    QCalendarWidget QToolButton {{ background: transparent; color: {TEXT}; icon-size: 16px; }}
    QCalendarWidget QMenu {{ background: {SURFACE}; color: {TEXT}; }}
    QCalendarWidget QSpinBox {{ background: {SURFACE}; color: {TEXT}; }}
    QCalendarWidget QAbstractItemView {{
        background: {SURFACE}; color: {TEXT}; outline: none;
        selection-background-color: {PIN}; selection-color: #FFFFFF;
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
            background = QColor(SELECTED_BG) if selected else QColor(SURFACE)
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
    taskDeleteRequested = Signal(str)  # 업무 id — Backspace/Delete로 삭제 요청
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
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsDragEnabled | Qt.ItemFlag.ItemIsDropEnabled)
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
                self.taskDeleteRequested.emit(item.data(ROLE_TASK_ID))
                event.accept()
                return
        super().keyPressEvent(event)

    def dragEnterEvent(self, event) -> None:
        if isinstance(event.source(), ColumnList):
            super().dragEnterEvent(event)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        if isinstance(event.source(), ColumnList):
            # 부모 클래스를 불러야 Qt가 드롭 위치 표시선(카테고리 목록 드래그할 때 보이는 것과
            # 같은 줄)을 계산하고 그려 줍니다. 이걸 안 부르면 표시선이 전혀 안 보였습니다.
            super().dragMoveEvent(event)
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
            # 카드 위/아래 빈 공간에 놓으면 여기 걸립니다. 맨 위 카드보다도 위쪽에 놓았으면
            # 맨 앞으로, 그 외(맨 아래 등)에는 맨 뒤로 보냅니다 — 안 그러면 맨 위로 옮기려는
            # 드래그가 항상 맨 뒤로 가버렸습니다.
            if self.count() > 0 and pos.y() < self.visualItemRect(self.item(0)).top():
                row = 0
            else:
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

        self.start_edit = QDateEdit()
        self.start_edit.setCalendarPopup(True)
        self.start_edit.setDisplayFormat("yyyy-MM-dd")
        style_calendar_popup(self.start_edit)
        if task and task.start:
            self.start_edit.setDate(QDate.fromString(task.start, "yyyy-MM-dd"))
        elif task and task.created_at:
            self.start_edit.setDate(QDate.fromString(task.created_at[:10], "yyyy-MM-dd"))
        else:
            self.start_edit.setDate(QDate.currentDate())  # 새 업무는 지금 등록하는 날짜가 기본값

        self.no_due = QCheckBox("마감일 없음")
        self.due_edit = QDateEdit()
        self.due_edit.setCalendarPopup(True)
        self.due_edit.setDisplayFormat("yyyy-MM-dd")
        style_calendar_popup(self.due_edit)
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
        form.addRow("시작일", self.start_edit)
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
            "start": self.start_edit.date().toString("yyyy-MM-dd"),
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

        theme_label = QLabel("테마")
        self.light_button = QPushButton("☀ 라이트")
        self.dark_button = QPushButton("🌙 다크")
        self.light_button.setCheckable(True)
        self.dark_button.setCheckable(True)
        self.light_button.clicked.connect(lambda: self._set_theme("light"))
        self.dark_button.clicked.connect(lambda: self._set_theme("dark"))
        current_theme = self.window.settings.get("theme", CURRENT_THEME)
        self.light_button.setChecked(current_theme == "light")
        self.dark_button.setChecked(current_theme != "light")

        theme_row = QHBoxLayout()
        theme_row.addWidget(self.light_button)
        theme_row.addWidget(self.dark_button)
        theme_row.addStretch(1)

        category_label = QLabel("카테고리 우선순위")

        # 목록과 추가/삭제 버튼을 하나의 테두리 안에 함께 담습니다. 목록 자체는 이 테두리
        # 안에서는 테두리가 없는 상태로 두고, 바깥 프레임에만 테두리를 그립니다.
        category_frame = QFrame()
        category_frame.setObjectName("categoryFrame")
        category_frame.setStyleSheet(
            f"QFrame#categoryFrame {{ border: 1px solid {BORDER}; border-radius: 8px; background: transparent; }}"
        )
        category_frame_layout = QVBoxLayout(category_frame)
        category_frame_layout.setContentsMargins(8, 8, 8, 8)
        category_frame_layout.setSpacing(6)

        self.category_list = QListWidget()
        self.category_list.setStyleSheet(
            "QListWidget { border: none; background: transparent; padding: 0px; }"
        )
        self.category_list.setFrameShape(QFrame.Shape.NoFrame)
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

        category_frame_layout.addWidget(self.category_list)
        category_frame_layout.addLayout(category_buttons)

        self._update_category_list_height()

        layout = QVBoxLayout(self)
        layout.addWidget(theme_label)
        layout.addLayout(theme_row)
        layout.addSpacing(10)
        layout.addWidget(category_label)
        layout.addWidget(category_frame)

    def _set_theme(self, name: str) -> None:
        self.light_button.setChecked(name == "light")
        self.dark_button.setChecked(name != "light")
        self.window.apply_theme(name)

    def _category_names(self) -> list[str]:
        return [self.category_list.item(i).text() for i in range(self.category_list.count())]

    def _update_category_list_height(self) -> None:
        """목록 테두리가 처음부터 크게 잡히지 않도록, 실제 항목 수에 맞춰 높이를 계산합니다.
        항목이 늘어나면 그만큼 늘어나고, 너무 많아지면(6개 초과) 그 이상은 스크롤로 봅니다."""
        count = self.category_list.count()
        row_height = self.category_list.sizeHintForRow(0)
        if row_height <= 0:
            row_height = self.category_list.fontMetrics().height() + 10
        max_visible = 6
        visible_rows = min(max(count, 1), max_visible)
        self.category_list.setFixedHeight(row_height * visible_rows + 8)

    def _add_category(self) -> None:
        name, ok = QInputDialog.getText(self, "카테고리 추가", "이름")
        name = name.strip()
        if not ok or not name or name in self._category_names():
            return
        self.category_list.addItem(name)
        self._update_category_list_height()
        self._sync()

    def _remove_category(self) -> None:
        row = self.category_list.currentRow()
        if row >= 0:
            self.category_list.takeItem(row)
            self._update_category_list_height()
            self._sync()

    def _sync(self) -> None:
        self.window.settings["categories"] = self._category_names()
        storage.save_settings(self.window.settings)
        self.window.reapply_rules()


CALENDAR_CHIP_PALETTE = [
    "#F7C6D0", "#F9DDB0", "#FBF0A9", "#C9E9C7", "#C6D9F7", "#DCC9F7",
    "#F7C9DC", "#C9F7EC", "#F7E1C6", "#D6F7C9", "#C9CFF7", "#F0C9F7",
]
WEEKDAY_LABELS = ["일", "월", "화", "수", "목", "금", "토"]
CALENDAR_MAX_LANES = 3  # 한 주에 동시에 겹쳐 보여줄 수 있는 색상줄 최대 개수
CALENDAR_DATE_ROW_HEIGHT = 26   # 날짜 숫자만 있는 줄의 최소 높이
CALENDAR_LANE_ROW_HEIGHT = 34   # 막대 한 줄의 최소 높이(여백 포함)
CALENDAR_BAR_OUTER_MARGIN = 6   # 날짜 숫자~첫 막대, 마지막 막대~칸 아래쪽 사이의 여유
CALENDAR_BAR_INNER_MARGIN = 1   # 막대와 막대 사이의 아주 살짝만 남기는 간격


def stable_palette_index(task_id: str, size: int) -> int:
    """업무 id(16진수 문자열)에서 뽑아낸, 언제 계산해도 항상 같은 팔레트 인덱스."""
    try:
        return int(task_id, 16) % size
    except ValueError:
        return sum(ord(c) for c in task_id) % size


def muted_chip_color(hex_color: str) -> str:
    """완료된 업무의 색상줄을 회색 쪽으로 살짝 바래게 만들어, 진행 중인(원색+볼드) 업무와
    한눈에 구분되게 합니다."""
    color = QColor(hex_color)
    gray = QColor(205, 205, 205)
    blended = QColor(
        (color.red() + gray.red() * 2) // 3,
        (color.green() + gray.green() * 2) // 3,
        (color.blue() + gray.blue() * 2) // 3,
    )
    return blended.name()


def weekday_text_color(column: int) -> str:
    """0=일요일은 은은한 빨강, 6=토요일은 은은한 파랑. 테마의 URGENT/PIN 톤을 그대로 재사용해서
    쨍하지 않고 라이트/다크 모두에서 자연스럽게 어울립니다."""
    if column == 0:
        return URGENT_OVERDUE
    if column == 6:
        return PIN
    return MUTED


class CalendarMonthView(QWidget):
    """완료한 대주제 업무를 시작일~마감일 구간의 색상줄로 월 달력에 보여줍니다.
    날짜 숫자를 누르면 dayClicked가 그 날짜를 알려줍니다."""

    dayClicked = Signal(object)  # datetime.date
    monthRendered = Signal()  # 달이 바뀌거나 다시 그려질 때마다 — 창 크기를 다시 맞추는 데 씁니다

    def __init__(self, window: "MainWindow", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.window = window
        today = date.today()
        self.current_year = today.year
        self.current_month = today.month
        self._day_cells: list[QWidget] = []

        self.year_button = QPushButton()
        self.year_button.setFont(ui_font(14, bold=True))
        self.year_button.setToolTip("연도 선택")
        self.year_button.clicked.connect(self._pick_year)
        self.month_button = QPushButton()
        self.month_button.setFont(ui_font(14, bold=True))
        self.month_button.setToolTip("월 선택")
        self.month_button.clicked.connect(self._pick_month)
        prev_button = QPushButton("◀")
        prev_button.setFixedWidth(32)
        prev_button.clicked.connect(lambda: self._shift_month(-1))
        next_button = QPushButton("▶")
        next_button.setFixedWidth(32)
        next_button.clicked.connect(lambda: self._shift_month(1))

        header = QHBoxLayout()
        header.addWidget(prev_button)
        header.addStretch(1)
        header.addWidget(self.year_button)
        header.addWidget(self.month_button)
        header.addStretch(1)
        header.addWidget(next_button)

        self.grid = QGridLayout()
        self.grid.setSpacing(0)  # 칸 사이 간격 없이 붙여서, 막대가 날짜를 넘나들 때 끊겨 보이지 않게 합니다
        for column, weekday_name in enumerate(WEEKDAY_LABELS):
            heading = QLabel(weekday_name)
            heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
            heading.setStyleSheet(
                f"color: {weekday_text_color(column)}; font-weight: 600;"
                f"border-bottom: 1px solid {BORDER}; padding-bottom: 6px;"
            )
            self.grid.addWidget(heading, 0, column)
            self.grid.setColumnStretch(column, 1)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addLayout(header)
        outer.addLayout(self.grid)

        self._render_month()

    def _shift_month(self, delta: int) -> None:
        month = self.current_month + delta
        year = self.current_year
        while month < 1:
            month += 12
            year -= 1
        while month > 12:
            month -= 12
            year += 1
        self.current_year, self.current_month = year, month
        self._render_month()

    def _pick_year(self) -> None:
        year, ok = QInputDialog.getInt(self, "연도 선택", "연도", self.current_year, 1970, 2100, 1)
        if ok:
            self.current_year = year
            self._render_month()

    def _pick_month(self) -> None:
        months = [f"{m}월" for m in range(1, 13)]
        choice, ok = QInputDialog.getItem(
            self, "월 선택", "월", months, self.current_month - 1, False
        )
        if ok:
            self.current_month = months.index(choice) + 1
            self._render_month()

    def _task_spans(self) -> list[tuple[Task, date, date, bool]]:
        """(업무, 시작일, 마감일, 완료여부) 튜플 목록. 대주제(최상위 업무) 중 기간을 알 수 있는
        것만 대상입니다. 완료된 업무는 마감일이 없으면 완료한 날을 대신 씁니다. 진행 중인 업무는
        마감일이 있어야 나옵니다(언제까지인지 알 수 없으면 막대를 그릴 수 없으므로)."""
        spans: list[tuple[Task, date, date, bool]] = []
        for task in self.window.tasks:
            if task.parent_id is not None:
                continue
            end = None
            if task.due:
                try:
                    end = date.fromisoformat(task.due)
                except ValueError:
                    end = None
            if end is None and task.done and task.done_at:
                try:
                    end = date.fromisoformat(task.done_at[:10])
                except ValueError:
                    end = None
            if end is None:
                continue
            start = end
            if task.start:
                try:
                    start = date.fromisoformat(task.start)
                except ValueError:
                    start = end
            if start > end:
                start, end = end, start
            spans.append((task, start, end, task.done))
        return spans

    def _render_month(self) -> None:
        self.year_button.setText(f"{self.current_year}년")
        self.month_button.setText(f"{self.current_month}월")
        for widget in self._day_cells:
            self.grid.removeWidget(widget)
            widget.deleteLater()
        self._day_cells.clear()

        cal = calendar_module.Calendar(firstweekday=6)  # 일요일 시작
        weeks = cal.monthdatescalendar(self.current_year, self.current_month)
        grid_start, grid_end = weeks[0][0], weeks[-1][-1]

        spans = self._task_spans()
        visible_spans = [(t, s, e, d) for t, s, e, d in spans if s <= grid_end and e >= grid_start]

        # 업무 id에서 뽑은 고정값으로 색을 정해서, 같은 업무는 달을 오갔다 와도 항상 같은 색이
        # 나오게 합니다(매번 무작위로 다시 섞으면 왔다 갔다 할 때마다 색이 바뀌어 버립니다).
        # 화면에 보이는 달 안에서만 겹치지 않으면 되므로, 같은 색이 우연히 겹치는 업무가
        # 있으면 다음 빈 자리로 밀어 넣습니다.
        seen_ids: set[str] = set()
        visible_ids: list[str] = []
        for task, _s, _e, _d in visible_spans:
            if task.id not in seen_ids:
                seen_ids.add(task.id)
                visible_ids.append(task.id)
        colors: dict[str, str] = {}
        used_indices: set[int] = set()
        for tid in visible_ids:
            index = stable_palette_index(tid, len(CALENDAR_CHIP_PALETTE))
            while index in used_indices:
                index = (index + 1) % len(CALENDAR_CHIP_PALETTE)
            used_indices.add(index)
            colors[tid] = CALENDAR_CHIP_PALETTE[index]

        # 1차: 주마다 실제로 필요한 lane 수만 먼저 계산합니다. 겹치는 업무가 적은 주는
        # 그만큼만 자리를 차지해서, 빈 줄이 여러 개 남는 이전 방식보다 표처럼 촘촘하게 나옵니다.
        week_plans = []
        for week in weeks:
            week_start, week_end = week[0], week[-1]
            overlapping = [
                (task, max(start, week_start), min(end, week_end), done)
                for task, start, end, done in visible_spans
                if start <= week_end and end >= week_start
            ]
            overlapping.sort(key=lambda item: item[1])
            lane_ends: list[date | None] = [None] * CALENDAR_MAX_LANES
            placed = []
            for task, seg_start, seg_end, done in overlapping:
                lane = next((i for i, e in enumerate(lane_ends) if e is None or e < seg_start), None)
                if lane is None:
                    continue  # 같은 주에 동시에 겹치는 업무가 lane 수보다 많으면 나머지는 생략합니다
                lane_ends[lane] = seg_end
                placed.append((task, seg_start, seg_end, lane, done))
            lanes_used = max((p[3] for p in placed), default=-1) + 1
            week_plans.append((week, placed, max(lanes_used, 1)))

        # 주마다 칸 높이가 다르면 마지막 줄처럼 유독 좁아 보이는 주가 생기므로, 이번 달에서
        # 가장 많이 겹치는 주를 기준으로 모든 주가 같은 줄 수(=같은 칸 크기)를 쓰게 맞춥니다.
        uniform_lanes = max((lp[2] for lp in week_plans), default=1)

        row_cursor = 1  # 0번 행은 요일 헤더
        for week, placed, _week_lanes in week_plans:
            lanes_used = uniform_lanes
            week_start = week[0]

            # 스팬 위젯(cell)의 minimumHeight만으로는 Qt가 날짜 줄/막대 줄에 높이를 어떻게
            # 나눌지 애매하게 처리해서, 업무가 늘어날수록 줄이 눌리며 날짜가 가려지곤 했습니다.
            # 그래서 각 행에 필요한 높이를 직접 지정해 확실하게 자리를 보장합니다.
            self.grid.setRowMinimumHeight(row_cursor, CALENDAR_DATE_ROW_HEIGHT)
            for lane in range(lanes_used):
                self.grid.setRowMinimumHeight(row_cursor + 1 + lane, CALENDAR_LANE_ROW_HEIGHT)

            # 표처럼 칸끼리 선이 맞닿게, 칸마다 오른쪽/아래 테두리만 그어서 격자를 만듭니다
            # (둥근 카드 대신 스프레드시트에 가까운 모양 — 요청하신 참고 이미지 스타일).
            for column, day in enumerate(week):
                in_month = day.month == self.current_month
                cell = QWidget()
                cell.setStyleSheet(f"background: {CANVAS};")
                cell_layout = QVBoxLayout(cell)
                cell_layout.setContentsMargins(6, 4, 0, 0)
                cell_layout.setSpacing(0)
                cell_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

                day_label = QLabel(str(day.day))
                if day == date.today():
                    day_label.setFixedSize(22, 22)
                    day_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    day_label.setStyleSheet(
                        "background-color: #e5484d; color: #ffffff;"
                        "font-weight: 700; border-radius: 11px;"
                    )
                else:
                    day_label.setStyleSheet(
                        f"color: {TEXT if in_month else MUTED}; font-weight: 600; background: transparent;"
                    )
                cell_layout.addWidget(day_label)

                cell.setCursor(Qt.CursorShape.PointingHandCursor)
                cell.mousePressEvent = lambda _event, d=day: self.dayClicked.emit(d)
                self.grid.addWidget(cell, row_cursor, column, 1 + lanes_used, 1)
                self._day_cells.append(cell)

            for task, seg_start, seg_end, lane, done in placed:
                col_start = (seg_start - week_start).days
                span_days = (seg_end - seg_start).days + 1
                base_color = colors.get(task.id, CALENDAR_CHIP_PALETTE[0])
                bar = QLabel()
                if done:
                    # 완료된 업무는 색을 살짝 바래게 해서 뒤로 물러나 보이게 합니다.
                    style = (
                        f"background: {muted_chip_color(base_color)}; color: #4A4A4A;"
                        "border-radius: 4px; font-weight: 500;"
                    )
                else:
                    # 진행 중인 업무는 원래 색 그대로 + 굵은 글씨 + 왼쪽 강조선으로 확실히 도드라지게 합니다.
                    style = (
                        f"background: {base_color}; color: #2B2B2B; font-weight: 700;"
                        f"border-radius: 4px; border-left: 3px solid {PIN};"
                    )
                # 막대 자체는 작게 유지하고, 막대끼리(같은 날 안에서)는 아주 살짝만 띄웁니다.
                # 대신 날짜 숫자와 첫 막대 사이, 마지막 막대와 칸 아래쪽 사이에는 여유를 넉넉히 둡니다.
                top_margin = CALENDAR_BAR_OUTER_MARGIN if lane == 0 else CALENDAR_BAR_INNER_MARGIN
                bottom_margin = (
                    CALENDAR_BAR_OUTER_MARGIN if lane == uniform_lanes - 1 else CALENDAR_BAR_INNER_MARGIN
                )
                bar.setStyleSheet(
                    f"{style} padding: 0px 6px; font-size: 11px;"
                    f"margin: {top_margin}px 2px {bottom_margin}px 2px;"
                )
                metrics = bar.fontMetrics()
                bar.setText(metrics.elidedText(task.title, Qt.TextElideMode.ElideRight, 96 * span_days))
                bar.setCursor(Qt.CursorShape.PointingHandCursor)
                self.grid.addWidget(bar, row_cursor + 1 + lane, col_start, 1, span_days)
                bar.raise_()
                self._day_cells.append(bar)

            # 주 사이 구분선은 날짜 칸(cell) 자체의 테두리로 그리지 않고, 이렇게 별도의 얇은
            # 위젯으로 그립니다. cell에 border-bottom을 직접 주면 Qt/Fusion 스타일에서 그
            # 안의 자식 위젯(날짜 숫자) 바로 밑에도 테두리가 겹쳐 그려지는 버그가 있었습니다.
            divider_row = row_cursor + 1 + lanes_used
            self.grid.setRowMinimumHeight(divider_row, 1)
            divider = QWidget()
            divider.setFixedHeight(1)
            divider.setStyleSheet(f"background: {BORDER};")
            self.grid.addWidget(divider, divider_row, 0, 1, len(WEEKDAY_LABELS))
            self._day_cells.append(divider)

            row_cursor = divider_row + 1

        self.monthRendered.emit()


class HistoryDialog(QDialog):
    """기간을 고르면 그 사이에 완료 처리한 업무를 쭉 보여줍니다."""

    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window)
        self.window = window
        self.setWindowTitle("완료 이력")
        self.setMinimumSize(640, 500)

        self.calendar_view = CalendarMonthView(window)
        self.calendar_view.dayClicked.connect(self._jump_to_day)
        # 달력은 줄이 늘어나도 눌리지 않고 항상 한 번에 다 보여야 하므로, 달력 자체를 스크롤에
        # 가두지 않고 창을 그만큼 키웁니다. 대신 아래 업무 목록은 자체 스크롤로 넘칩니다.
        self.calendar_view.monthRendered.connect(self._fit_window_to_calendar)

        self.start_edit = QDateEdit()
        self.start_edit.setCalendarPopup(True)
        self.start_edit.setDisplayFormat("yyyy-MM-dd")
        style_calendar_popup(self.start_edit)
        self.start_edit.setDate(QDate.currentDate().addDays(-7))
        self.end_edit = QDateEdit()
        self.end_edit.setCalendarPopup(True)
        self.end_edit.setDisplayFormat("yyyy-MM-dd")
        style_calendar_popup(self.end_edit)
        self.end_edit.setDate(QDate.currentDate())
        self.start_edit.dateChanged.connect(self._refresh)
        self.end_edit.dateChanged.connect(self._refresh)

        range_row = QHBoxLayout()
        range_row.addWidget(QLabel("시작일"))
        range_row.addWidget(self.start_edit, 1)
        range_row.addWidget(QLabel("완료일"))
        range_row.addWidget(self.end_edit, 1)

        self.result_tree = QTreeWidget()
        self.result_tree.setHeaderHidden(True)
        self.result_tree.setIndentation(16)
        self.result_tree.setMinimumHeight(150)  # adjustSize()가 목록을 너무 눌러버리지 않게 최소 높이 확보

        layout = QVBoxLayout(self)
        layout.addWidget(self.calendar_view)
        layout.addSpacing(12)
        layout.addLayout(range_row)
        layout.addWidget(self.result_tree, 1)

        self._refresh()
        self._fit_window_to_calendar()

    def _fit_window_to_calendar(self) -> None:
        """달력 줄 수가 바뀌면(월 이동, 연/월 선택) 창 높이를 다시 맞춥니다.
        달력은 항상 통째로 보이고, 목록 쪽만 스크롤로 넘치게 하려는 목적입니다."""
        self.calendar_view.updateGeometry()
        needed = self.layout().totalMinimumSize().height()
        if self.height() < needed:
            self.resize(self.width(), needed)

    def _jump_to_day(self, day: date) -> None:
        """달력 칸을 누르면 그 날 하루로 아래 목록을 좁혀서 보여줍니다."""
        target = QDate(day.year, day.month, day.day)
        with QSignalBlocker(self.start_edit):
            self.start_edit.setDate(target)
        self.end_edit.setDate(target)  # end_edit의 dateChanged가 _refresh를 한 번만 트리거합니다

    def _tasks_in_range(self, start: date, end: date) -> list[Task]:
        items = []
        for task in self.window.tasks:
            if not task.done or not task.done_at:
                continue
            try:
                done_date = date.fromisoformat(task.done_at[:10])
            except ValueError:
                continue
            if start <= done_date <= end:
                items.append(task)
        return sorted(items, key=lambda t: t.done_at)

    def _children_for(self, parent_id: str) -> list[Task]:
        children = [t for t in self.window.tasks if t.parent_id == parent_id and t.done]
        return sorted(children, key=lambda t: t.done_at or "")

    @staticmethod
    def _row_text(task: Task) -> str:
        stamp = task.done_at[:10] if task.done_at else "?"
        return f"{stamp}  ·  {task.title}"

    def _refresh(self) -> None:
        start = self.start_edit.date().toPython()
        end = self.end_edit.date().toPython()
        self.result_tree.clear()
        tasks = self._tasks_in_range(start, end) if start <= end else []
        in_range_ids = {t.id for t in tasks}
        # 부모가 이 기간 목록에 없으면(완료 안 됐거나 범위 밖) 하위 업무를 고아로 두지 않고
        # 최상위처럼 그대로 보여줍니다.
        top_level = [t for t in tasks if t.parent_id is None or t.parent_id not in in_range_ids]
        top_level.sort(key=lambda t: t.done_at or "")

        if not top_level:
            placeholder = QTreeWidgetItem(["이 기간에 완료한 업무가 없습니다."])
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self.result_tree.addTopLevelItem(placeholder)
            return

        for task in top_level:
            row = QTreeWidgetItem([self._row_text(task)])
            for child in self._children_for(task.id):
                row.addChild(QTreeWidgetItem([self._row_text(child)]))
            self.result_tree.addTopLevelItem(row)


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
        self.column_name_labels: dict[str, QLabel] = {}
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
        history_button = QPushButton("📅")
        history_button.setToolTip("완료 이력 보기 (기간별로 완료한 업무 확인)")
        history_button.clicked.connect(self.open_history)
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
        toolbar.addWidget(history_button)
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
        self.done_toggle.setText("TODO목록" if self.show_done else "완료 항목 보기")
        self._apply_done_label()
        self.lists[TODO].setDragEnabled(not self.show_done)
        self.lists[TODO].setAcceptDrops(not self.show_done)

        tbd_collapsed = bool(self.settings.get("tbd_collapsed", False))
        with QSignalBlocker(self.collapse_button):
            self.collapse_button.setChecked(tbd_collapsed)
        self._refresh_tbd_visibility()

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
        name.setStyleSheet(f"color: {column_accent(column)};")
        self.column_name_labels[column] = name
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
        listing.taskDeleteRequested.connect(self.on_task_delete_requested)
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
        return any(t.parent_id == task_id and not t.archived for t in self.tasks)

    def top_level_tasks(self, column: str) -> list[Task]:
        """완료된 업무도 (지우기 전까지는) 여기 그대로 남아 있습니다 — DONE 화면과 동시에 보입니다.
        TODO/TBD 화면에서 뺀(archived) 업무만 여기서 사라집니다."""
        items = [t for t in self.tasks if t.column == column and t.parent_id is None and not t.archived]
        return sorted(items, key=lambda t: (t.done, t.checked, self.category_rank(t), t.order))

    def child_tasks(self, parent_id: str) -> list[Task]:
        items = [t for t in self.tasks if t.parent_id == parent_id and not t.archived]
        return sorted(items, key=lambda t: (t.done, t.checked, t.order))

    def visible_tasks(self, column: str) -> list[Task]:
        """부모 다음에 그 하위 업무들이 이어지는, 화면에 그릴 순서 그대로의 목록."""
        result: list[Task] = []
        for parent in self.top_level_tasks(column):
            result.append(parent)
            if not parent.collapsed:
                result.extend(self.child_tasks(parent.id))
        return result

    def done_top_level_tasks(self) -> list[Task]:
        """TODO/TBD 구분 없이, 완료된 최상위 업무를 모읍니다."""
        items = [t for t in self.tasks if t.done and t.parent_id is None]
        return sorted(items, key=lambda t: (self.category_rank(t), t.order))

    def done_child_tasks(self, parent_id: str) -> list[Task]:
        """완료된 업무의 하위 업무 중에서도 완료된 것만 (DONE 화면에는 완료된 것만 보여주므로)."""
        items = [t for t in self.tasks if t.parent_id == parent_id and t.done]
        return sorted(items, key=lambda t: t.order)

    def done_tasks(self) -> list[Task]:
        """TODO 화면과 똑같이, 대주제 다음에 그 하위 업무들이 바로 이어지는 순서로 묶어서 돌려줍니다."""
        result: list[Task] = []
        shown_children: set[str] = set()
        for parent in self.done_top_level_tasks():
            result.append(parent)
            children = self.done_child_tasks(parent.id)
            if children and not parent.collapsed:
                result.extend(children)
            shown_children.update(c.id for c in children)
        # 상위 업무가 완료되지 않았거나(또는 이미 지워졌거나) 해서 위 루프에 안 낀 완료된 하위
        # 업무는 고아로 남기지 않고 최상위처럼 그대로 보여줍니다.
        orphans = [
            t for t in self.tasks
            if t.done and t.parent_id is not None and t.id not in shown_children
        ]
        orphans.sort(key=lambda t: (self.category_rank(t), t.order))
        result.extend(orphans)
        return result

    def render(self) -> None:
        for column, listing in self.lists.items():
            selected_id = None
            current = listing.currentItem()
            if current:
                selected_id = current.data(ROLE_TASK_ID)
            listing.clear()
            if self.show_done:
                tasks = self.done_tasks() if column == TODO else []
            else:
                tasks = self.visible_tasks(column)
            for task in tasks:
                item = QListWidgetItem()
                item.setData(ROLE_TASK_ID, task.id)
                item.setData(ROLE_CARD, self._card(task, in_done_view=self.show_done))
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsDragEnabled | Qt.ItemFlag.ItemIsDropEnabled)
                listing.addItem(item)
                if task.id == selected_id:
                    listing.setCurrentItem(item)
            pinned = sum(1 for t in tasks if t.pinned)
            label = str(len(tasks)) + (f" · 고정 {pinned}" if pinned else "")
            self.counters[column].setText(label)

    def _card(self, task: Task, in_done_view: bool = False) -> dict:
        parts = []
        if task.category:
            parts.append(f"[{task.category}]")
        parts.append(due_caption(task))
        if task.tags:
            parts.append(" ".join(f"#{t}" for t in task.tags))
        children = [t for t in self.tasks if t.parent_id == task.id and not t.archived]
        if children:
            # 체크박스만 눌러도(완료 처리까지는 안 갔어도) "다 했다"는 뜻으로 보고 숫자에 반영합니다.
            done_children = sum(1 for t in children if t.checked or t.done)
            parts.append(f"하위 {done_children}/{len(children)}")
        return {
            "title": task.title,
            "meta": "  ·  ".join(parts),
            "pinned": task.pinned,
            "checked": task.checked,
            "done": task.done,
            "urgency": task_urgency(task),
            "indent": 1 if task.parent_id else 0,
            # DONE 화면에서는 완료된 하위 업무만 그 아래 나오니, 화살표도 완료된 하위가 있을 때만 보여줍니다.
            "has_children": bool(self.done_child_tasks(task.id)) if in_done_view else bool(children),
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

    def _infer_drop_parent(self, column: str, task_id: str, row: int) -> str | None:
        """같은 칸 안에서 순서만 바꿔 놓았을 때, 놓인 위치 바로 위 카드를 보고 새
        parent_id를 정합니다 — 하위 업무 카드 바로 다음에 놓으면 그 부모의 하위로 남고,
        최상위 카드 바로 다음(또는 맨 위)에 놓으면 다시 최상위로 돌아옵니다. 이게 없으면
        한 번 하위로 들어간 업무는 같은 칸 안에서 순서만 바꿔도 계속 하위에 갇혀 있었습니다."""
        flat = [t for t in self.visible_tasks(column) if t.id != task_id]
        row = max(0, min(row, len(flat)))
        if row == 0:
            return None
        anchor = flat[row - 1]
        if anchor.parent_id is not None:
            return anchor.parent_id
        # anchor가 최상위 업무인 경우: 바로 다음 카드가 그 하위 업무라면(부모와 첫 하위
        # 업무 사이에 끼워 넣는 상황) 최상위로 튀어나오지 않고 그 하위로 들어가게 합니다.
        if row < len(flat) and flat[row].parent_id == anchor.id:
            return anchor.id
        return None

    def on_task_dropped(self, task_id: str, column: str, row: int, moved_across: bool) -> None:
        task = self.find(task_id)
        if task is None:
            return
        if moved_across:
            task.column = column
            task.pinned = True
            task.parent_id = None
        else:
            task.parent_id = self._infer_drop_parent(column, task_id, row)
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
        self.done_toggle.setText("TODO목록" if checked else "완료 항목 보기")
        self._apply_done_label()
        self.lists[TODO].setDragEnabled(not checked)
        self.lists[TODO].setAcceptDrops(not checked)
        self._refresh_tbd_visibility()
        self.render()

    def _apply_done_label(self) -> None:
        """DONE 화면을 보는 동안은 TODO 칸 이름 자체가 'DONE'으로 바뀌고, TBD는 숨겨져서
        완료된 업무를 TODO/TBD 구분 없이 한 목록으로 봅니다."""
        label = self.column_name_labels[TODO]
        if self.show_done:
            label.setText("DONE")
            label.setStyleSheet(f"color: {DONE_GREEN};")
        else:
            label.setText(COLUMN_LABEL[TODO])
            label.setStyleSheet(f"color: {column_accent(TODO)};")

    def _refresh_tbd_visibility(self) -> None:
        """DONE 화면을 보는 동안에는 TBD를 항상 숨깁니다. DONE 화면을 벗어나면 사용자가 직접
        접어둔 상태(collapse_button)로 되돌립니다. 여기서는 창 크기를 바꾸지 않습니다 —
        DONE 보기를 켰다 껐다 할 때마다 창이 들썩이지 않게 하기 위해서입니다."""
        visible = not self.show_done and not self.collapse_button.isChecked()
        self.column_wrappers[TBD].setVisible(visible)
        self.expand_button.setVisible((not visible) and not self.show_done)
        self._apply_collapsed_spacing(not visible)
        self.board.activate()

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
        if task.done and not self.show_done:
            # TODO/TBD 화면에서 완료된 카드를 지우는 경우: 완전히 지우지 않고 그 화면에서만 뺍니다.
            # DONE 화면·완료 이력에서는 계속 볼 수 있습니다.
            message = f"'{task.title}'을(를) 목록에서 뺄까요? DONE 화면·완료 이력에서는 계속 확인할 수 있습니다."
            answer = QMessageBox.question(self, "목록에서 빼기", message)
            if answer != QMessageBox.StandardButton.Yes:
                return
            task.archived = True
            for child in children:
                child.archived = True
            self.persist()
            self.render()
            return

        message = (
            f"'{task.title}'을(를) 완전히 지울까요? 완료 이력에서도 사라집니다."
            if task.done
            else f"'{task.title}'을(를) 지울까요?"
        )
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
        task.done_at = datetime.now().isoformat(timespec="seconds") if done else None
        if not done:
            task.archived = False  # 완료를 취소하면 다시 TODO/TBD 화면에 보여야 합니다
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
        self.set_done(task, not task.done)

    def on_task_delete_requested(self, task_id: str) -> None:
        task = self.find(task_id)
        if task is None:
            return
        self.delete_task(task)

    def reapply_rules(self) -> None:
        self.rules, _ = storage.load_rules()
        apply_rules(self.tasks, self.rules)
        self.persist()
        self.render()

    def open_settings(self) -> None:
        dialog = SettingsDialog(self)
        dialog.exec()
        self.render()

    def open_history(self) -> None:
        dialog = HistoryDialog(self)
        dialog.exec()

    def apply_theme(self, name: str) -> None:
        apply_theme(name)
        QApplication.instance().setStyleSheet(app_stylesheet())
        self._apply_done_label()
        self.column_name_labels[TBD].setStyleSheet(f"color: {column_accent(TBD)};")
        self.settings["theme"] = CURRENT_THEME
        storage.save_settings(self.settings)
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
    apply_theme(storage.load_settings().get("theme", CURRENT_THEME))
    app.setStyleSheet(app_stylesheet())
    window = MainWindow()
    window.show()
    return app.exec()
