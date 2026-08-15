"""
Events and Sentiment Dimension

事件与情绪维度：财报、公告、新闻、催化与风险事件。
"""

from ..evidence.schemas import EvidencePack, Horizon
from .base import DimensionAnalyzer, DimensionOpinion


class EventsSentimentAnalyzer(DimensionAnalyzer):
    """事件与情绪分析器"""
    dimension_id = "events_and_sentiment"
    required_evidence = [
        'events_earnings_dates', 'events_dividends',
        'news_headlines', 'news_sentiment_score',
    ]

    def analyze(self, evidence_pack: EvidencePack, indicators: dict, horizon: Horizon) -> DimensionOpinion:
        available, missing = self._check_evidence(evidence_pack)
        confidence = self._calculate_confidence(len(available), len(self.required_evidence))

        if confidence < 0.3:
            return DimensionOpinion(
                dimension_id=self.dimension_id,
                horizon=horizon,
                status='unavailable',
                direction=None,
                confidence=confidence,
                thesis='事件和新闻数据不足',
                evidence_ids=available,
                missing_evidence_ids=missing,
            )

        direction = 'neutral'
        thesis_parts = []

        # 新闻情绪
        sentiment = evidence_pack.get_item('news_sentiment_score')
        if sentiment and sentiment.value is not None:
            try:
                score = float(sentiment.value)
                if score > 0.3:
                    direction = 'bullish'
                    thesis_parts.append(f"新闻情绪正面 ({score:.2f})")
                elif score < -0.3:
                    direction = 'bearish'
                    thesis_parts.append(f"新闻情绪负面 ({score:.2f})")
                else:
                    thesis_parts.append(f"新闻情绪中性 ({score:.2f})")
            except (ValueError, TypeError):
                pass

        thesis = '；'.join(thesis_parts) if thesis_parts else '事件和情绪中性'

        return DimensionOpinion(
            dimension_id=self.dimension_id,
            horizon=horizon,
            status='success' if confidence >= 0.6 else 'degraded',
            direction=direction,
            confidence=confidence,
            thesis=thesis,
            evidence_ids=available,
            missing_evidence_ids=missing,
            warnings=['部分事件与情绪证据缺失'] if confidence < 0.6 else [],
        )
