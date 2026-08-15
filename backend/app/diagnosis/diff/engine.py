"""
Version Diff Engine

版本对比引擎。
"""

from dataclasses import dataclass, field


@dataclass
class EvidenceDiff:
    """证据变化"""
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    changed: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            'added': self.added,
            'removed': self.removed,
            'changed': self.changed,
        }


@dataclass
class ProfileDiff:
    """画像变化"""
    changes: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {'changes': self.changes}


@dataclass
class MethodDiff:
    """方法变化"""
    model_changed: bool = False
    prompt_changed: bool = False
    rule_changed: bool = False
    provider_changed: bool = False

    def to_dict(self) -> dict:
        return {
            'model_changed': self.model_changed,
            'prompt_changed': self.prompt_changed,
            'rule_changed': self.rule_changed,
            'provider_changed': self.provider_changed,
        }


@dataclass
class AdviceDiff:
    """建议变化"""
    action_changed: bool = False
    old_action: str = ""
    new_action: str = ""
    confidence_changed: bool = False
    old_confidence: float = 0.0
    new_confidence: float = 0.0
    conditions_changed: bool = False

    def to_dict(self) -> dict:
        return {
            'action_changed': self.action_changed,
            'old_action': self.old_action,
            'new_action': self.new_action,
            'confidence_changed': self.confidence_changed,
            'old_confidence': self.old_confidence,
            'new_confidence': self.new_confidence,
            'conditions_changed': self.conditions_changed,
        }


@dataclass
class VersionDiff:
    """版本对比结果"""
    evidence_diff: EvidenceDiff = field(default_factory=EvidenceDiff)
    profile_diff: ProfileDiff = field(default_factory=ProfileDiff)
    method_diff: MethodDiff = field(default_factory=MethodDiff)
    advice_diff: AdviceDiff = field(default_factory=AdviceDiff)

    def to_dict(self) -> dict:
        return {
            'evidence_diff': self.evidence_diff.to_dict(),
            'profile_diff': self.profile_diff.to_dict(),
            'method_diff': self.method_diff.to_dict(),
            'advice_diff': self.advice_diff.to_dict(),
        }


class DiffEngine:
    """Diff 引擎"""

    def diff(
        self,
        version_a: dict,
        version_b: dict,
    ) -> VersionDiff:
        """
        对比两个版本

        Args:
            version_a: 版本 A 数据
            version_b: 版本 B 数据

        Returns:
            版本对比结果
        """
        return VersionDiff(
            evidence_diff=self._diff_evidence(version_a, version_b),
            profile_diff=self._diff_profile(version_a, version_b),
            method_diff=self._diff_method(version_a, version_b),
            advice_diff=self._diff_advice(version_a, version_b),
        )

    def _diff_evidence(self, v1: dict, v2: dict) -> EvidenceDiff:
        """对比证据"""
        e1 = v1.get('evidence', {})
        e2 = v2.get('evidence', {})

        added = [k for k in e2 if k not in e1]
        removed = [k for k in e1 if k not in e2]
        changed = []

        for k in e1:
            if k in e2 and e1[k] != e2[k]:
                changed.append({
                    'evidence_id': k,
                    'old_value': e1[k],
                    'new_value': e2[k],
                })

        return EvidenceDiff(added=added, removed=removed, changed=changed)

    def _diff_profile(self, v1: dict, v2: dict) -> ProfileDiff:
        """对比画像"""
        p1 = v1.get('decision_profile', {})
        p2 = v2.get('decision_profile', {})

        changes = []
        for k in set(list(p1.keys()) + list(p2.keys())):
            if p1.get(k) != p2.get(k):
                changes.append({
                    'field': k,
                    'old_value': p1.get(k),
                    'new_value': p2.get(k),
                })

        return ProfileDiff(changes=changes)

    def _diff_method(self, v1: dict, v2: dict) -> MethodDiff:
        """对比方法"""
        m1 = v1.get('provenance', {})
        m2 = v2.get('provenance', {})

        return MethodDiff(
            model_changed=m1.get('model_id') != m2.get('model_id'),
            prompt_changed=m1.get('prompt_version') != m2.get('prompt_version'),
            rule_changed=m1.get('rule_version') != m2.get('rule_version'),
            provider_changed=m1.get('providers_used') != m2.get('providers_used'),
        )

    def _diff_advice(self, v1: dict, v2: dict) -> AdviceDiff:
        """对比建议"""
        a1 = v1.get('advice', {}).get('conclusion', {})
        a2 = v2.get('advice', {}).get('conclusion', {})

        return AdviceDiff(
            action_changed=a1.get('action') != a2.get('action'),
            old_action=a1.get('action', ''),
            new_action=a2.get('action', ''),
            confidence_changed=a1.get('confidence') != a2.get('confidence'),
            old_confidence=a1.get('confidence', 0),
            new_confidence=a2.get('confidence', 0),
            conditions_changed=(
                a1.get('triggering_conditions') != a2.get('triggering_conditions')
                or a1.get('invalidating_conditions') != a2.get('invalidating_conditions')
            ),
        )
