from __future__ import annotations

from io import BytesIO
from datetime import datetime
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak

# 中文 PDF 字体：ReportLab 内置 CID Font，不依赖系统字体。
pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))


class Report2568PdfBuilder:
    """2568 标注 PDF 报表生成器 - 重点样本全字段解读版。

    目标：
    1. 主表保持紧凑，避免横向裁切。
    2. “重点样本解读”章节完整展示每只样本的全部关键字段。
    3. PDF 中将 Emoji 替换为 [A]/[B]/[C]/[D]/[OK]，避免乱码。
    """

    def __init__(self, data: dict[str, Any], params: dict[str, Any]):
        self.data = data or {}
        self.params = params or {}
        self.items = list(self.data.get("items") or [])
        self.summary = self.data.get("summary") or {}
        self.styles = self._styles()

    def build(self) -> bytes:
        buf = BytesIO()
        doc = SimpleDocTemplate(
            buf,
            pagesize=landscape(A4),
            rightMargin=10 * mm,
            leftMargin=10 * mm,
            topMargin=10 * mm,
            bottomMargin=10 * mm,
            title="2568标注报表解读",
        )
        story = []
        story.extend(self._cover())
        story.extend(self._summary_section())
        story.extend(self._interpretation_section())
        story.extend(self._compact_table_section())
        story.extend(self._detail_section())
        doc.build(story, onFirstPage=self._footer, onLaterPages=self._footer)
        return buf.getvalue()

    def _styles(self):
        base = getSampleStyleSheet()
        return {
            "title": ParagraphStyle("title_cn", parent=base["Title"], fontName="STSong-Light", fontSize=22, leading=28, alignment=TA_CENTER, spaceAfter=10),
            "h1": ParagraphStyle("h1_cn", parent=base["Heading1"], fontName="STSong-Light", fontSize=15, leading=20, spaceBefore=8, spaceAfter=8),
            "h2": ParagraphStyle("h2_cn", parent=base["Heading2"], fontName="STSong-Light", fontSize=12, leading=16, spaceBefore=6, spaceAfter=5),
            "body": ParagraphStyle("body_cn", parent=base["BodyText"], fontName="STSong-Light", fontSize=9.5, leading=14, alignment=TA_LEFT),
            "small": ParagraphStyle("small_cn", parent=base["BodyText"], fontName="STSong-Light", fontSize=7.4, leading=9.2, alignment=TA_LEFT),
            "cell": ParagraphStyle("cell_cn", parent=base["BodyText"], fontName="STSong-Light", fontSize=7.0, leading=8.4, alignment=TA_LEFT),
            "cell_bold": ParagraphStyle("cell_bold_cn", parent=base["BodyText"], fontName="STSong-Light", fontSize=7.2, leading=8.6, alignment=TA_LEFT),
            "detail_label": ParagraphStyle("detail_label_cn", parent=base["BodyText"], fontName="STSong-Light", fontSize=7.5, leading=9.2, alignment=TA_LEFT, textColor=colors.HexColor("#334155")),
            "detail_value": ParagraphStyle("detail_value_cn", parent=base["BodyText"], fontName="STSong-Light", fontSize=7.5, leading=9.2, alignment=TA_LEFT),
        }

    def _cover(self):
        p = self.params
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return [
            Paragraph("2568标注报表解读", self.styles["title"]),
            Paragraph("纯标注版 + 亮点总结 + A/B/C/D 分级筛选", self.styles["body"]),
            Spacer(1, 8),
            Paragraph(f"生成时间：{now}", self.styles["body"]),
            Paragraph(
                f"筛选参数：market_type={p.get('market_type', 'all')}；limit={p.get('limit', '')}；"
                f"summary={p.get('summary') or '全部'}；manual_action={p.get('manual_action') or '全部'}；"
                f"min_a={p.get('min_a') or '-'}；min_b={p.get('min_b') or '-'}；min_d={p.get('min_d') or '-'}；risk_only={p.get('risk_only', 0)}",
                self.styles["body"],
            ),
            Spacer(1, 8),
            Paragraph("说明：本报告仅用于结构化行情分析与人工复盘，不构成任何投资建议；报告不进行打分、排序或自动剔除。", self.styles["body"]),
            Spacer(1, 10),
        ]

    def _summary_section(self):
        by_label = self.summary.get("by_label") or {}
        by_action = self.summary.get("by_action") or {}
        total = self.summary.get("total", len(self.items))
        rows = [
            ["指标", "数量"],
            ["总记录数", str(total)],
            ["强满足", str(by_label.get("强满足", 0))],
            ["临界", str(by_label.get("临界", 0))],
            ["弱满足", str(by_label.get("弱满足", 0))],
            ["强势票｜重点关注", str(by_action.get("强势票｜重点关注", 0))],
            ["有核心亮点｜可关注", str(by_action.get("有核心亮点｜可关注", 0))],
            ["风险较多｜建议移出", str(by_action.get("风险较多｜建议移出", 0))],
        ]
        table = Table(rows, colWidths=[70 * mm, 35 * mm])
        table.setStyle(self._table_style(header=True))
        return [Paragraph("一、汇总概览", self.styles["h1"]), table, Spacer(1, 8)]

    def _interpretation_section(self):
        total = max(int(self.summary.get("total") or len(self.items) or 0), 1)
        by_action = self.summary.get("by_action") or {}
        focus = int(by_action.get("强势票｜重点关注", 0))
        watch = int(by_action.get("有核心亮点｜可关注", 0))
        mid = int(by_action.get("中强票｜观察池", 0)) + int(by_action.get("健康趋势｜可观察", 0))
        risk = int(by_action.get("风险较多｜建议移出", 0)) + int(by_action.get("风险偏多｜谨慎观察", 0))

        story = [Paragraph("二、报表解读", self.styles["h1"])]
        bullets = [
            f"重点关注样本占比约 {focus / total * 100:.1f}%：A 级亮点数量较多，适合优先人工查看结构细节。",
            f"可关注样本占比约 {(watch + mid) / total * 100:.1f}%：具备一定趋势或结构亮点，适合加入观察池。",
            f"风险偏多样本占比约 {risk / total * 100:.1f}%：需要重点检查 D 级风险，例如 MA25 下弯、MA60 下行、结构破位、加速段或连续缩量。",
            "人工复盘建议顺序：先看 A≥2，再看 A≥1，再看 B≥2/B≥3，最后检查 D≥2/D≥3 风险项。",
        ]
        for b in bullets:
            story.append(Paragraph("• " + b, self.styles["body"]))
        story.append(Spacer(1, 8))
        return story

    def _compact_table_section(self):
        story = [Paragraph("三、核心明细表（最多展示前 120 条）", self.styles["h1"])]
        rows = [["代码", "名称", "人工建议", "等级", "A", "B", "D", "亮点摘要", "主要风险"]]
        for r in self.items[:120]:
            rows.append([
                self._para(r.get("code"), "cell"),
                self._para(r.get("name"), "cell"),
                self._para(r.get("manual_action_label"), "cell_bold"),
                self._para(r.get("highlight_level"), "cell"),
                self._para(r.get("a_count"), "cell"),
                self._para(r.get("b_count"), "cell"),
                self._para(r.get("d_count"), "cell"),
                self._para(self._clean(r.get("highlight_summary")), "cell"),
                self._para(self._clean(r.get("d_highlights") or r.get("risk_tags")), "cell"),
            ])
        table = Table(
            rows,
            repeatRows=1,
            colWidths=[18 * mm, 24 * mm, 36 * mm, 15 * mm, 9 * mm, 9 * mm, 9 * mm, 100 * mm, 56 * mm],
        )
        table.setStyle(self._table_style(header=True))
        story.append(table)
        story.append(Spacer(1, 8))
        return story

    def _detail_section(self):
        """重点样本解读：完整展开所有人工复盘关键字段。"""
        if not self.items:
            return []
        story = [PageBreak(), Paragraph("四、重点样本解读（前 30 条，完整字段）", self.styles["h1"])]
        for idx, r in enumerate(self.items[:30], 1):
            title = f"{idx}. {self._s(r.get('code'))} {self._s(r.get('name'))}｜{self._s(r.get('manual_action_label'))}｜等级 {self._s(r.get('highlight_level'))}"
            story.append(Paragraph(title, self.styles["h2"]))

            detail_rows = [
                ["代码", self._s(r.get("code")), "名称", self._s(r.get("name")), "日期", self._s(r.get("date"))],
                ["人工建议", self._s(r.get("manual_action_label")), "等级", self._s(r.get("highlight_level")), "总结", self._s(r.get("summary_label"))],
                ["A/B/C/D数量", f"A={self._s(r.get('a_count'))} / B={self._s(r.get('b_count'))} / C={self._s(r.get('c_count'))} / D={self._s(r.get('d_count'))}", "收盘", self._s(r.get("close")), "量比", self._s(r.get("vol_ratio"))],
                ["亮点总结", self._clean(r.get("highlight_summary")), "风险", self._clean(r.get("risk_tags")), "D风险", self._clean(r.get("d_highlights"))],
                ["A亮点", self._clean(r.get("a_highlights")), "B亮点", self._clean(r.get("b_highlights")), "C参考", self._clean(r.get("c_highlights"))],
                ["趋势亮点", self._clean(r.get("trend_highlight")), "量能亮点", self._clean(r.get("volume_highlight")), "结构亮点", self._clean(r.get("structure_highlight"))],
                ["安全亮点", self._clean(r.get("safety_highlight")), "风险亮点", self._clean(r.get("risk_highlight")), "", ""],
                ["MA25", self._clean(r.get("ma25_status")), "MA60", self._clean(r.get("ma60_status")), "价格", self._clean(r.get("price_status"))],
                ["量能", self._clean(r.get("volume_status")), "趋势", self._clean(r.get("trend_status")), "回踩", self._clean(r.get("pullback_status"))],
                ["MA25斜率", self._clean(r.get("slope25_status")), "MA60斜率", self._clean(r.get("slope60_status")), "量能强弱", self._clean(r.get("volume_strength_status"))],
                ["K线位置", self._clean(r.get("kline_position_status")), "MA25数值", self._s(r.get("ma25")), "MA60数值", self._s(r.get("ma60"))],
            ]
            wrapped_rows = []
            for row in detail_rows:
                wrapped_rows.append([
                    self._para(row[0], "detail_label"), self._para(row[1], "detail_value"),
                    self._para(row[2], "detail_label"), self._para(row[3], "detail_value"),
                    self._para(row[4], "detail_label"), self._para(row[5], "detail_value"),
                ])
            table = Table(
                wrapped_rows,
                colWidths=[18 * mm, 73 * mm, 18 * mm, 73 * mm, 18 * mm, 73 * mm],
                hAlign="LEFT",
            )
            table.setStyle(TableStyle([
                ("FONTNAME", (0, 0), (-1, -1), "STSong-Light"),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d8dee9")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f1f5f9")),
                ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#f1f5f9")),
                ("BACKGROUND", (4, 0), (4, -1), colors.HexColor("#f1f5f9")),
                ("LEFTPADDING", (0, 0), (-1, -1), 2.2),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2.2),
                ("TOPPADDING", (0, 0), (-1, -1), 2.2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2.2),
            ]))
            story.append(table)
            story.append(Spacer(1, 6))
        return story

    def _table_style(self, header: bool = False):
        style = TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), "STSong-Light"),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
            ("LEADING", (0, 0), (-1, -1), 8.4),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d8dee9")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 2.2),
            ("RIGHTPADDING", (0, 0), (-1, -1), 2.2),
            ("TOPPADDING", (0, 0), (-1, -1), 2.2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2.2),
        ])
        if header:
            style.add("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8f0fe"))
            style.add("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#0f172a"))
            style.add("FONTSIZE", (0, 0), (-1, 0), 7.8)
        return style

    def _footer(self, canvas, doc):
        canvas.saveState()
        canvas.setFont("STSong-Light", 8)
        canvas.setFillColor(colors.HexColor("#64748b"))
        canvas.drawString(10 * mm, 7 * mm, "2568标注报表解读｜仅用于结构化分析与人工复盘")
        canvas.drawRightString(287 * mm, 7 * mm, f"第 {doc.page} 页")
        canvas.restoreState()

    def _para(self, value, style="cell"):
        return Paragraph(self._clean(value), self.styles[style])

    @staticmethod
    def _s(v) -> str:
        if v is None or v == "":
            return "-"
        return str(v)

    def _clean(self, value) -> str:
        s = self._s(value)
        repl = {
            "⭐": "[A]",
            "🔥": "[A]",
            "🟩": "[A]",
            "🟦": "[B]",
            "⚠": "[D]",
            "❌": "[D]",
            "✘": "[D]",
            "✔": "[OK]",
            "~": "[C]",
        }
        for k, v in repl.items():
            s = s.replace(k, v)
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
