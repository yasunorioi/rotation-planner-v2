"""
最適化モジュール
OR-Tools CP-SAT / ヒューリスティックによる輪作計画最適化
"""

import numpy as np
import random
from typing import Dict, List, Tuple, Optional
from copy import deepcopy
from ortools.sat.python import cp_model

from .utils import Field, UNKNOWN_MARKER, generate_future_years, load_csv
from .utils import generate_result_tables, generate_csv_content
from .constraints import (
    Constraints, FIXED_FORBIDDEN_TRANSITIONS,
    parse_constraints_table, parse_forbidden_transitions, parse_preferred_transitions
)


# =============================================================================
# ヒューリスティック最適化
# =============================================================================

class RotationPlannerHeuristic:
    """輪作計画最適化クラス（ヒューリスティック版）"""

    def __init__(self, fields: List[Field], past_years: List[str],
                 future_years: List[str], crops: List[str], constraints: Constraints):
        self.fields = fields
        self.past_years = past_years
        self.future_years = future_years
        self.all_years = past_years + future_years
        self.crops = crops
        self.constraints = constraints
        self.errors = []

    def get_last_n_crops(self, field_idx: int, year: str, n: int, plan: Dict) -> List[str]:
        """指定年から過去n年の作付を取得"""
        year_idx = self.all_years.index(year)
        crops_list = []
        for i in range(1, n + 1):
            if year_idx - i >= 0:
                prev_year = self.all_years[year_idx - i]
                if prev_year in self.past_years:
                    crops_list.append(self.fields[field_idx].history.get(prev_year, UNKNOWN_MARKER))
                else:
                    crops_list.append(plan.get((field_idx, prev_year), UNKNOWN_MARKER))
        return crops_list

    def check_gap_constraint(self, field_idx: int, year: str, crop: str, plan: Dict) -> bool:
        """間隔制約をチェック"""
        min_gap = self.constraints.min_gap_years.get(crop, 0)
        if min_gap <= 0:
            return True

        past_crops = self.get_last_n_crops(field_idx, year, min_gap, plan)

        for pc in past_crops:
            if pc == crop:
                return False
            if pc == UNKNOWN_MARKER and self.constraints.unknown_mode == "safe":
                return False

        return True

    def check_transition_constraint(self, field_idx: int, year: str, crop: str, plan: Dict) -> bool:
        """遷移制約をチェック（連作禁止含む）"""
        prev_crops = self.get_last_n_crops(field_idx, year, 1, plan)
        if not prev_crops:
            return True

        prev_crop = prev_crops[0]

        if prev_crop == UNKNOWN_MARKER:
            if self.constraints.unknown_mode == "safe":
                for (from_c, to_c) in self.constraints.forbidden_transitions:
                    if to_c == crop:
                        return False
            return True

        # 連作禁止
        if prev_crop == crop:
            return False

        # 禁止遷移
        if (prev_crop, crop) in self.constraints.forbidden_transitions:
            return False

        return True

    def check_adjacency_constraint(self, field_idx: int, year: str, crop: str, plan: Dict) -> bool:
        """隣接筆の同一科制約をチェック（PRO機能）"""
        if not self.constraints.adjacent_family_enabled:
            return True
        family = self.constraints.crop_family_map.get(crop)
        if not family:
            return True
        for fi, fj in self.constraints.adjacency_pairs:
            neighbor_idx = None
            if fi == field_idx:
                neighbor_idx = fj
            elif fj == field_idx:
                neighbor_idx = fi
            if neighbor_idx is not None:
                neighbor_crop = plan.get((neighbor_idx, year))
                if neighbor_crop:
                    neighbor_family = self.constraints.crop_family_map.get(neighbor_crop)
                    if neighbor_family and neighbor_family == family:
                        return False
        return True

    def get_valid_crops(self, field_idx: int, year: str, plan: Dict) -> List[str]:
        """有効な作物リストを取得"""
        valid = []
        for crop in self.crops:
            if self.check_gap_constraint(field_idx, year, crop, plan):
                if self.check_transition_constraint(field_idx, year, crop, plan):
                    if self.check_adjacency_constraint(field_idx, year, crop, plan):
                        valid.append(crop)
        return valid

    def calculate_year_stats(self, year: str, plan: Dict) -> Dict[str, Tuple[float, int]]:
        """年の作物統計を計算: {crop: (total_ha, field_count)}"""
        stats = {c: (0.0, 0) for c in self.crops}
        for i, f in enumerate(self.fields):
            if year in self.past_years:
                crop = f.history.get(year, UNKNOWN_MARKER)
            else:
                crop = plan.get((i, year), None)

            if crop and crop != UNKNOWN_MARKER and crop in stats:
                ha, cnt = stats[crop]
                stats[crop] = (ha + f.area_ha, cnt + 1)

        return stats

    def check_cap_constraint(self, year: str, crop: str, plan: Dict,
                             additional_ha: float = 0) -> bool:
        """面積上限をチェック (0は無制限)"""
        cap = self.constraints.crop_caps.get(crop)
        if cap is None or cap == 0:
            return True

        stats = self.calculate_year_stats(year, plan)
        current_ha = stats.get(crop, (0, 0))[0]
        return current_ha + additional_ha <= cap

    def check_field_count_constraint(self, year: str, crop: str, plan: Dict,
                                     adding: bool = False) -> Tuple[bool, str]:
        """ほ場数制約をチェック"""
        min_f = self.constraints.min_fields.get(crop, 0)
        max_f = self.constraints.max_fields.get(crop)

        stats = self.calculate_year_stats(year, plan)
        current_count = stats.get(crop, (0, 0))[1]

        if adding:
            new_count = current_count + 1
        else:
            new_count = current_count

        if max_f is not None and new_count > max_f:
            return False, f"{crop}のほ場数が上限({max_f})を超えます"

        return True, ""

    def calculate_transition_score(self, field_idx: int, year: str, crop: str, plan: Dict) -> float:
        """遷移スコアを計算"""
        prev_crops = self.get_last_n_crops(field_idx, year, 1, plan)
        if not prev_crops or prev_crops[0] == UNKNOWN_MARKER:
            return 0

        prev_crop = prev_crops[0]
        return self.constraints.preferred_transitions.get((prev_crop, crop), 0)

    def calculate_gap_bonus(self, field_idx: int, year: str, crop: str, plan: Dict) -> float:
        """間隔ボーナス（てんさい/馬鈴薯など）"""
        min_gap = self.constraints.min_gap_years.get(crop, 0)
        if min_gap <= 0:
            return 0

        year_idx = self.all_years.index(year)
        actual_gap = 0
        for i in range(1, len(self.all_years)):
            if year_idx - i < 0:
                break
            prev_year = self.all_years[year_idx - i]
            if prev_year in self.past_years:
                prev_crop = self.fields[field_idx].history.get(prev_year, UNKNOWN_MARKER)
            else:
                prev_crop = plan.get((field_idx, prev_year), None)

            if prev_crop == crop:
                break
            actual_gap += 1

        return max(0, actual_gap - min_gap) * 0.5

    def evaluate_solution(self, plan: Dict) -> Tuple[float, List[str]]:
        """解の評価"""
        score = 0.0
        violations = []

        # 各年の統計
        year_stats = {}
        for year in self.future_years:
            year_stats[year] = self.calculate_year_stats(year, plan)

        # 1. 主作物の面積変動を評価
        for crop in self.constraints.main_crops:
            areas = [year_stats[y].get(crop, (0, 0))[0] for y in self.future_years]
            if areas:
                variance = np.var(areas)
                score -= variance * 10

        # 2. 優先遷移スコア
        for i, f in enumerate(self.fields):
            for year in self.future_years:
                crop = plan.get((i, year))
                if crop:
                    score += self.calculate_transition_score(i, year, crop, plan)
                    score += self.calculate_gap_bonus(i, year, crop, plan)

        # 3. 制約違反チェック
        for year in self.future_years:
            stats = year_stats[year]

            for crop in self.crops:
                # 面積上限
                cap = self.constraints.crop_caps.get(crop)
                if cap is not None and cap > 0:
                    ha = stats.get(crop, (0, 0))[0]
                    if ha > cap:
                        violations.append(f"{year}: {crop}の面積({ha:.2f}ha)が上限({cap}ha)を超過")
                        score -= 100

                # ほ場数制約
                min_f = self.constraints.min_fields.get(crop, 0)
                max_f = self.constraints.max_fields.get(crop)
                cnt = stats.get(crop, (0, 0))[1]

                if cnt < min_f:
                    violations.append(f"{year}: {crop}のほ場数({cnt})が下限({min_f})未満")
                    score -= 50

                if max_f is not None and cnt > max_f:
                    violations.append(f"{year}: {crop}のほ場数({cnt})が上限({max_f})超過")
                    score -= 50

        return score, violations

    def generate_initial_solution(self) -> Dict[Tuple[int, str], str]:
        """初期解を生成"""
        plan = {}

        for year in self.future_years:
            field_indices = list(range(len(self.fields)))
            random.shuffle(field_indices)

            for field_idx in field_indices:
                valid_crops = self.get_valid_crops(field_idx, year, plan)

                if not valid_crops:
                    valid_crops = self.crops.copy()
                    self.errors.append(f"警告: ほ場{self.fields[field_idx].field_id}の{year}で制約を満たす作物がありません")

                best_crop = None
                best_score = float('-inf')

                for crop in valid_crops:
                    if not self.check_cap_constraint(year, crop, plan, self.fields[field_idx].area_ha):
                        continue

                    ok, _ = self.check_field_count_constraint(year, crop, plan, adding=True)
                    if not ok:
                        continue

                    score = self.calculate_transition_score(field_idx, year, crop, plan)
                    score += self.calculate_gap_bonus(field_idx, year, crop, plan)
                    score += random.random() * 0.1

                    if score > best_score:
                        best_score = score
                        best_crop = crop

                if best_crop is None:
                    best_crop = random.choice(valid_crops) if valid_crops else self.crops[0]

                plan[(field_idx, year)] = best_crop

        return plan

    def local_search(self, plan: Dict, max_iterations: int = 1000) -> Dict:
        """局所探索で解を改善"""
        current_plan = deepcopy(plan)
        current_score, _ = self.evaluate_solution(current_plan)

        for _ in range(max_iterations):
            field_idx = random.randint(0, len(self.fields) - 1)
            year = random.choice(self.future_years)

            valid_crops = self.get_valid_crops(field_idx, year, current_plan)
            if not valid_crops:
                continue

            old_crop = current_plan.get((field_idx, year))
            new_crop = random.choice(valid_crops)

            if new_crop == old_crop:
                continue

            current_plan[(field_idx, year)] = new_crop

            if not self.check_cap_constraint(year, new_crop, current_plan):
                current_plan[(field_idx, year)] = old_crop
                continue

            ok, _ = self.check_field_count_constraint(year, new_crop, current_plan)
            if not ok:
                current_plan[(field_idx, year)] = old_crop
                continue

            new_score, _ = self.evaluate_solution(current_plan)

            if new_score > current_score:
                current_score = new_score
            else:
                current_plan[(field_idx, year)] = old_crop

        return current_plan

    def ensure_min_fields(self, plan: Dict) -> Dict:
        """最小ほ場数制約を満たすように調整"""
        for year in self.future_years:
            stats = self.calculate_year_stats(year, plan)

            for crop in self.crops:
                min_f = self.constraints.min_fields.get(crop, 0)
                if min_f <= 0:
                    continue

                current_count = stats.get(crop, (0, 0))[1]

                while current_count < min_f:
                    changed = False
                    for i, f in enumerate(self.fields):
                        current_crop = plan.get((i, year))
                        if current_crop == crop:
                            continue

                        if not self.check_gap_constraint(i, year, crop, plan):
                            continue
                        if not self.check_transition_constraint(i, year, crop, plan):
                            continue

                        if current_crop:
                            other_min = self.constraints.min_fields.get(current_crop, 0)
                            other_stats = self.calculate_year_stats(year, plan)
                            if other_stats.get(current_crop, (0, 0))[1] <= other_min:
                                continue

                        plan[(i, year)] = crop
                        changed = True
                        current_count += 1
                        break

                    if not changed:
                        self.errors.append(f"警告: {year}の{crop}最小ほ場数({min_f})を満たせません")
                        break

        return plan

    def solve(self) -> Tuple[Dict, float, List[str]]:
        """最適化を実行"""
        self.errors = []

        plan = self.generate_initial_solution()
        plan = self.local_search(plan, max_iterations=2000)
        plan = self.ensure_min_fields(plan)

        score, violations = self.evaluate_solution(plan)
        all_errors = self.errors + violations

        return plan, score, all_errors


# =============================================================================
# OR-Tools CP-SAT最適化
# =============================================================================

class RotationPlannerORTools:
    """輪作計画最適化クラス（OR-Tools CP-SAT版）"""

    def __init__(self, fields: List[Field], past_years: List[str],
                 future_years: List[str], crops: List[str], constraints: Constraints):
        self.fields = fields
        self.past_years = past_years
        self.future_years = future_years
        self.all_years = past_years + future_years
        self.crops = crops
        self.constraints = constraints
        self.num_fields = len(fields)
        self.num_crops = len(crops)
        self.num_future_years = len(future_years)
        self.crop_to_idx = {c: i for i, c in enumerate(crops)}
        self.idx_to_crop = {i: c for i, c in enumerate(crops)}
        self.heuristic = RotationPlannerHeuristic(fields, past_years, future_years, crops, constraints)

    def get_past_crop_idx(self, field_idx: int, year_offset: int) -> Optional[int]:
        """過去の作付を取得（year_offset: 1=前年, 2=前々年, ...）"""
        if not self.past_years:
            return None
        target_year_idx = len(self.past_years) - year_offset
        if target_year_idx < 0:
            return None
        target_year = self.past_years[target_year_idx]
        crop = self.fields[field_idx].history.get(target_year, UNKNOWN_MARKER)
        if crop == UNKNOWN_MARKER:
            return None
        return self.crop_to_idx.get(crop)

    def solve(self, timeout_seconds: int = 10, high_precision: bool = False,
              district_grouping: bool = True) -> Tuple[Dict, float, List[str]]:
        """OR-Toolsで最適化を実行"""
        model = cp_model.CpModel()

        # 決定変数
        x = {}
        for f in range(self.num_fields):
            for y in range(self.num_future_years):
                for c in range(self.num_crops):
                    x[f, y, c] = model.NewBoolVar(f'x_{f}_{y}_{c}')

        # 制約1: 各ほ場・各年に1作物のみ
        for f in range(self.num_fields):
            for y in range(self.num_future_years):
                model.Add(sum(x[f, y, c] for c in range(self.num_crops)) == 1)

        # 制約2: 連作禁止（将来年同士）
        for f in range(self.num_fields):
            for y in range(self.num_future_years - 1):
                for c in range(self.num_crops):
                    model.Add(x[f, y, c] + x[f, y + 1, c] <= 1)

        # 制約3: 連作禁止（過去→将来1年目）
        for f in range(self.num_fields):
            last_crop_idx = self.get_past_crop_idx(f, 1)
            if last_crop_idx is not None:
                model.Add(x[f, 0, last_crop_idx] == 0)

        # 制約4: 禁止遷移（将来年同士）
        for (from_crop, to_crop) in self.constraints.forbidden_transitions:
            from_idx = self.crop_to_idx.get(from_crop)
            to_idx = self.crop_to_idx.get(to_crop)
            if from_idx is None or to_idx is None:
                continue
            for f in range(self.num_fields):
                for y in range(self.num_future_years - 1):
                    model.Add(x[f, y, from_idx] + x[f, y + 1, to_idx] <= 1)

        # 制約5: 禁止遷移（過去→将来1年目）
        for f in range(self.num_fields):
            last_crop_idx = self.get_past_crop_idx(f, 1)
            if last_crop_idx is not None:
                last_crop = self.idx_to_crop[last_crop_idx]
                for (from_crop, to_crop) in self.constraints.forbidden_transitions:
                    if from_crop == last_crop:
                        to_idx = self.crop_to_idx.get(to_crop)
                        if to_idx is not None:
                            model.Add(x[f, 0, to_idx] == 0)

        # 制約6: 間隔制約
        for c in range(self.num_crops):
            crop_name = self.idx_to_crop[c]
            min_gap = self.constraints.min_gap_years.get(crop_name, 0)
            if min_gap <= 0:
                continue

            for f in range(self.num_fields):
                for offset in range(1, min_gap + 1):
                    past_idx = self.get_past_crop_idx(f, offset)
                    if past_idx == c:
                        for y in range(min(min_gap - offset + 1, self.num_future_years)):
                            model.Add(x[f, y, c] == 0)
                        break

                for y1 in range(self.num_future_years):
                    for y2 in range(y1 + 1, min(y1 + min_gap + 1, self.num_future_years)):
                        model.Add(x[f, y1, c] + x[f, y2, c] <= 1)

        # ソフト制約用の違反変数
        cap_over = {}
        max_total_area = int(sum(f.area_ha for f in self.fields) * 100) + 1

        for c in range(self.num_crops):
            crop_name = self.idx_to_crop[c]
            cap = self.constraints.crop_caps.get(crop_name)
            if cap is not None and cap > 0:
                cap_int = int(cap * 100)
                for y in range(self.num_future_years):
                    cap_over[c, y] = model.NewIntVar(0, max_total_area, f'cap_over_{c}_{y}')
                    area_sum = sum(int(self.fields[f].area_ha * 100) * x[f, y, c]
                                   for f in range(self.num_fields))
                    model.Add(cap_over[c, y] >= area_sum - cap_int)

        cap_under = {}
        for c in range(self.num_crops):
            crop_name = self.idx_to_crop[c]
            min_ha = self.constraints.crop_mins.get(crop_name)
            if min_ha is not None and min_ha > 0:
                min_int = int(min_ha * 100)
                for y in range(self.num_future_years):
                    cap_under[c, y] = model.NewIntVar(0, max_total_area, f'cap_under_{c}_{y}')
                    area_sum = sum(int(self.fields[f].area_ha * 100) * x[f, y, c]
                                   for f in range(self.num_fields))
                    model.Add(cap_under[c, y] >= min_int - area_sum)

        field_over = {}
        field_under = {}

        for c in range(self.num_crops):
            crop_name = self.idx_to_crop[c]
            min_f = self.constraints.min_fields.get(crop_name, 0)
            max_f = self.constraints.max_fields.get(crop_name)

            for y in range(self.num_future_years):
                count = sum(x[f, y, c] for f in range(self.num_fields))

                if min_f > 0:
                    field_under[c, y] = model.NewIntVar(0, self.num_fields, f'field_under_{c}_{y}')
                    model.Add(field_under[c, y] >= min_f - count)

                if max_f is not None:
                    field_over[c, y] = model.NewIntVar(0, self.num_fields, f'field_over_{c}_{y}')
                    model.Add(field_over[c, y] >= count - max_f)

        # 制約9: ばれいしょ・てんさい禁止ほ場（FAMIC表記）
        beet_idx = self.crop_to_idx.get("てんさい")
        potato_idx = self.crop_to_idx.get("ばれいしょ")
        for f_idx, fld in enumerate(self.fields):
            if fld.beet_forbidden:
                for y in range(self.num_future_years):
                    if beet_idx is not None:
                        model.Add(x[f_idx, y, beet_idx] == 0)
                    if potato_idx is not None:
                        model.Add(x[f_idx, y, potato_idx] == 0)

        # 制約10: 隣接筆の同一科禁止（PRO機能 - ソフト制約）
        PENALTY_ADJACENT_FAMILY = 200000
        adj_over = {}
        if self.constraints.adjacent_family_enabled and self.constraints.adjacency_pairs:
            # 科→作物インデックスリストを構築
            family_to_crop_indices: Dict[str, List[int]] = {}
            for crop_name, family in self.constraints.crop_family_map.items():
                c_idx = self.crop_to_idx.get(crop_name)
                if c_idx is not None:
                    family_to_crop_indices.setdefault(family, []).append(c_idx)

            for pair_idx, (fi, fj) in enumerate(self.constraints.adjacency_pairs):
                if fi >= self.num_fields or fj >= self.num_fields:
                    continue
                for y in range(self.num_future_years):
                    for family, crop_indices in family_to_crop_indices.items():
                        if len(crop_indices) < 1:
                            continue
                        # sum_fi = ほ場fiでこの科に属する作物が選ばれている数（0 or 1）
                        sum_fi = sum(x[fi, y, c] for c in crop_indices)
                        sum_fj = sum(x[fj, y, c] for c in crop_indices)
                        # both_same = 両方がこの科 → sum_fi + sum_fj >= 2
                        over_var = model.NewIntVar(
                            0, 1, f'adj_over_{pair_idx}_{y}_{family}')
                        model.Add(over_var >= sum_fi + sum_fj - 1)
                        adj_over[pair_idx, y, family] = over_var

        # 目的関数
        area_cy = {}
        for c in range(self.num_crops):
            for y in range(self.num_future_years):
                area_cy[c, y] = sum(int(self.fields[f].area_ha * 100) * x[f, y, c]
                                    for f in range(self.num_fields))

        max_area = int(sum(f.area_ha for f in self.fields) * 100) + 1
        diffs = []
        for c in range(self.num_crops):
            for y in range(self.num_future_years - 1):
                diff = model.NewIntVar(0, max_area, f'diff_{c}_{y}')
                model.Add(diff >= area_cy[c, y + 1] - area_cy[c, y])
                model.Add(diff >= area_cy[c, y] - area_cy[c, y + 1])
                diffs.append(diff)

        range_penalties = []
        for c in range(self.num_crops):
            area_max = model.NewIntVar(0, max_area, f'area_max_{c}')
            area_min = model.NewIntVar(0, max_area, f'area_min_{c}')
            for y in range(self.num_future_years):
                model.Add(area_max >= area_cy[c, y])
                model.Add(area_min <= area_cy[c, y])
            range_penalty = model.NewIntVar(0, max_area, f'range_{c}')
            model.Add(range_penalty == area_max - area_min)
            range_penalties.append(range_penalty)

        PENALTY_CAP_OVER = 100000
        PENALTY_CAP_UNDER = 500000
        PENALTY_FIELD_OVER = 500000
        PENALTY_FIELD_UNDER = 500000

        objective = []

        for key, var in cap_over.items():
            objective.append(PENALTY_CAP_OVER * var)
        for key, var in cap_under.items():
            objective.append(PENALTY_CAP_UNDER * var)
        for key, var in field_over.items():
            objective.append(PENALTY_FIELD_OVER * var)
        for key, var in field_under.items():
            objective.append(PENALTY_FIELD_UNDER * var)
        for key, var in adj_over.items():
            objective.append(PENALTY_ADJACENT_FAMILY * var)

        for diff in diffs:
            objective.append(diff)
        for rp in range_penalties:
            objective.append(2 * rp)

        # 地区まとめボーナス
        if district_grouping:
            districts = list(set(f.district for f in self.fields if f.district))
            if districts:
                district_fields = {d: [i for i, f in enumerate(self.fields) if f.district == d]
                                   for d in districts}

                BONUS_DISTRICT_GROUP = -50

                for d_idx, district in enumerate(districts):
                    field_indices = district_fields[district]
                    if len(field_indices) < 2:
                        continue

                    for y in range(self.num_future_years):
                        for c in range(self.num_crops):
                            count_var = model.NewIntVar(0, len(field_indices),
                                f'dcc_{d_idx}_{y}_{c}')
                            model.Add(count_var == sum(x[f, y, c] for f in field_indices))

                            is_grouped = model.NewBoolVar(f'grouped_{d_idx}_{y}_{c}')
                            model.Add(count_var >= 2).OnlyEnforceIf(is_grouped)
                            model.Add(count_var < 2).OnlyEnforceIf(is_grouped.Not())
                            objective.append(BONUS_DISTRICT_GROUP * is_grouped)

        model.Minimize(sum(objective))

        # ソルバー実行
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = timeout_seconds
        if high_precision:
            solver.parameters.num_search_workers = 4
            solver.parameters.linearization_level = 2
        status = solver.Solve(model)

        if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
            plan = {}
            for f in range(self.num_fields):
                for y in range(self.num_future_years):
                    year_name = self.future_years[y]
                    for c in range(self.num_crops):
                        if solver.Value(x[f, y, c]) == 1:
                            plan[(f, year_name)] = self.idx_to_crop[c]
                            break

            total_diff = solver.ObjectiveValue() / 100.0
            errors = []
            if status == cp_model.FEASIBLE:
                errors.append("注意: 最適解ではなく実行可能解です")

            for (c, y), var in cap_over.items():
                over_val = solver.Value(var)
                if over_val > 0:
                    crop_name = self.idx_to_crop[c]
                    year_name = self.future_years[y]
                    over_ha = over_val / 100.0
                    errors.append(f"⚠️ 警告: {year_name}の{crop_name}が面積上限を{over_ha:.2f}ha超過")

            for (c, y), var in cap_under.items():
                under_val = solver.Value(var)
                if under_val > 0:
                    crop_name = self.idx_to_crop[c]
                    year_name = self.future_years[y]
                    under_ha = under_val / 100.0
                    errors.append(f"⚠️ 警告: {year_name}の{crop_name}が面積下限を{under_ha:.2f}ha不足")

            for (c, y), var in field_over.items():
                over_val = solver.Value(var)
                if over_val > 0:
                    crop_name = self.idx_to_crop[c]
                    year_name = self.future_years[y]
                    errors.append(f"⚠️ 警告: {year_name}の{crop_name}がほ場数上限を{over_val}超過")

            for (c, y), var in field_under.items():
                under_val = solver.Value(var)
                if under_val > 0:
                    crop_name = self.idx_to_crop[c]
                    year_name = self.future_years[y]
                    errors.append(f"⚠️ 警告: {year_name}の{crop_name}がほ場数下限を{under_val}不足")

            for (pair_idx, y, family), var in adj_over.items():
                over_val = solver.Value(var)
                if over_val > 0:
                    fi, fj = self.constraints.adjacency_pairs[pair_idx]
                    field1 = self.fields[fi].field_id if fi < len(self.fields) else f"F{fi}"
                    field2 = self.fields[fj].field_id if fj < len(self.fields) else f"F{fj}"
                    year_name = self.future_years[y]
                    errors.append(f"⚠️ 警告: {year_name}に{field1}と{field2}で同一科({family})")

            return plan, -total_diff, errors
        else:
            return self.heuristic.solve()


# =============================================================================
# 感度分析
# =============================================================================

def run_sensitivity_analysis(fields: List[Field], past_years: List[str],
                             future_years: List[str], crops: List[str],
                             base_constraints: Constraints, base_score: float,
                             timeout_seconds: int = 1, max_tests: int = 5) -> List[str]:
    """
    各制約を少し緩めて再計算し、スコア改善度を比較。
    ボトルネックとなっている制約を特定する。
    """
    results = []
    relaxations = []

    for crop in crops:
        cap = base_constraints.crop_caps.get(crop)
        if cap is not None and cap > 0:
            relaxations.append({
                'type': 'cap_ha',
                'crop': crop,
                'original': cap,
                'relaxed': cap + 2,
                'description': f"{crop}のcap_ha: {cap}ha → {cap+2}ha"
            })

    for crop in crops:
        max_f = base_constraints.max_fields.get(crop)
        if max_f is not None and max_f > 0:
            relaxations.append({
                'type': 'max_fields',
                'crop': crop,
                'original': max_f,
                'relaxed': max_f + 1,
                'description': f"{crop}のmax_fields: {max_f} → {max_f+1}"
            })

    for crop in crops:
        gap = base_constraints.min_gap_years.get(crop, 0)
        if gap > 1:
            relaxations.append({
                'type': 'min_gap_years',
                'crop': crop,
                'original': gap,
                'relaxed': gap - 1,
                'description': f"{crop}のmin_gap_years: {gap}年 → {gap-1}年"
            })

    for crop in crops:
        min_ha = base_constraints.crop_mins.get(crop)
        if min_ha is not None and min_ha > 0:
            new_val = max(0, min_ha - 1)
            relaxations.append({
                'type': 'min_ha',
                'crop': crop,
                'original': min_ha,
                'relaxed': new_val,
                'description': f"{crop}のmin_ha: {min_ha}ha → {new_val}ha"
            })

    relaxations = relaxations[:max_tests]

    if not relaxations:
        return ["📊 ボトルネック分析: 緩和可能な制約がありません"]

    improvements = []

    for relax in relaxations:
        new_constraints = Constraints(
            crop_mins=dict(base_constraints.crop_mins),
            crop_caps=dict(base_constraints.crop_caps),
            min_gap_years=dict(base_constraints.min_gap_years),
            min_fields=dict(base_constraints.min_fields),
            max_fields=dict(base_constraints.max_fields),
            forbidden_transitions=set(base_constraints.forbidden_transitions),
            preferred_transitions=dict(base_constraints.preferred_transitions),
            main_crops=list(base_constraints.main_crops),
            unknown_mode=base_constraints.unknown_mode,
            adjacent_family_enabled=base_constraints.adjacent_family_enabled,
            adjacency_pairs=list(base_constraints.adjacency_pairs),
            crop_family_map=dict(base_constraints.crop_family_map),
        )

        crop = relax['crop']
        if relax['type'] == 'cap_ha':
            new_constraints.crop_caps[crop] = relax['relaxed']
        elif relax['type'] == 'min_ha':
            new_constraints.crop_mins[crop] = relax['relaxed'] if relax['relaxed'] > 0 else None
        elif relax['type'] == 'max_fields':
            new_constraints.max_fields[crop] = relax['relaxed']
        elif relax['type'] == 'min_fields':
            new_constraints.min_fields[crop] = relax['relaxed']
        elif relax['type'] == 'min_gap_years':
            new_constraints.min_gap_years[crop] = relax['relaxed']

        try:
            planner = RotationPlannerORTools(fields, past_years, future_years, crops, new_constraints)
            _, new_score, _ = planner.solve(timeout_seconds=timeout_seconds, high_precision=False)

            improvement = new_score - base_score
            if improvement > 0.1:
                improvements.append({
                    'description': relax['description'],
                    'improvement': improvement,
                    'new_score': new_score
                })
        except Exception:
            pass

    improvements.sort(key=lambda x: x['improvement'], reverse=True)

    if improvements:
        results.append("📊 **ボトルネック分析結果**（制約緩和による改善度）:")
        for i, imp in enumerate(improvements[:5]):
            pct = (imp['improvement'] / abs(base_score) * 100) if base_score != 0 else 0
            results.append(f"  {i+1}. {imp['description']} → スコア +{imp['improvement']:.1f} ({pct:.1f}%改善)")
    else:
        results.append("📊 ボトルネック分析: 制約緩和による大きな改善は見つかりませんでした")

    return results


# =============================================================================
# メイン最適化関数
# =============================================================================

def run_optimization(n_years, crop_text, constraints_table,
                    forbidden_text, preferred_text, main_crops_text, unknown_mode,
                    tensai_required, precision_mode, infer_unknown_flag, district_grouping,
                    adjacent_family_enabled,
                    fields: List[Field], past_years: List[str]):
    """最適化を実行

    Args:
        n_years: 将来年数
        crop_text: 作物リスト（改行区切り）
        constraints_table: 制約テーブル
        forbidden_text: 追加禁止遷移
        preferred_text: 優先遷移
        main_crops_text: 主作物
        unknown_mode: 空欄の扱い
        tensai_required: てんさい必須フラグ
        precision_mode: 計算精度
        infer_unknown_flag: 空欄推論フラグ
        district_grouping: 地区まとめフラグ
        adjacent_family_enabled: 隣接筆の同一科制約フラグ（PRO機能）
        fields: ほ場リスト
        past_years: 過去年リスト
    """
    from .utils import infer_unknown_crops

    if not fields:
        return None, None, None, "エラー: ほ場データがありません"

    # 作物リスト
    crops = [c.strip() for c in crop_text.strip().split('\n') if c.strip()]
    if not crops:
        return None, None, None, "エラー: 作物マスターが空です"

    # 将来年
    future_years = generate_future_years(past_years, int(n_years))

    # 制約パース
    crop_mins, crop_caps, min_gap, min_f, max_f = parse_constraints_table(constraints_table)

    # てんさい必須チェックボックスがONの場合
    if tensai_required:
        min_f["てんさい"] = 1

    # 禁止遷移
    forbidden = set(FIXED_FORBIDDEN_TRANSITIONS)
    forbidden.update(parse_forbidden_transitions(forbidden_text))

    # 空欄を推論で埋める
    if infer_unknown_flag:
        fields = infer_unknown_crops(fields, crops, forbidden)

    # 優先遷移
    preferred = parse_preferred_transitions(preferred_text)

    # 主作物
    main_crops = [c.strip() for c in main_crops_text.split(',') if c.strip()]

    # unknown_mode
    unk_mode = "safe" if "安全側" in unknown_mode else "ignore"

    # PRO: 隣接筆の同一科制約
    adjacency_pairs_idx = []
    crop_family_map = {}
    if adjacent_family_enabled:
        try:
            from rotation_planner.common import CropMasterRepository
            from rotation_planner.common.db_access import get_db
            from rotation_planner.field.spatial import get_adjacent_field_pairs

            # 作物→科マッピング取得
            crop_family_map = CropMasterRepository.get_family_map()

            # ほ場のfield_idリストを取得（fieldsはField dataclass）
            field_id_to_idx = {f.field_id: i for i, f in enumerate(fields)}

            # ほ場の座標データ取得（DBから全ほ場を取得）
            # field_idはDB上のfield_codeに対応
            all_db_fields = []
            with get_db() as conn:
                field_ids = list(field_id_to_idx.keys())
                placeholders = ','.join('?' * len(field_ids))
                cursor = conn.execute(f"""
                    SELECT field_code, coordinates_json FROM fields
                    WHERE field_code IN ({placeholders})
                """, field_ids)
                all_db_fields = [dict(row) for row in cursor.fetchall()]

            # 隣接ペア取得
            adj_pairs = get_adjacent_field_pairs(all_db_fields)

            # field_code→field_indexに変換
            for code_a, code_b in adj_pairs:
                idx_a = field_id_to_idx.get(code_a)
                idx_b = field_id_to_idx.get(code_b)
                if idx_a is not None and idx_b is not None:
                    adjacency_pairs_idx.append((idx_a, idx_b))
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"隣接制約の構築に失敗: {e}")

    constraints = Constraints(
        crop_mins=crop_mins,
        crop_caps=crop_caps,
        min_gap_years=min_gap,
        min_fields=min_f,
        max_fields=max_f,
        forbidden_transitions=forbidden,
        preferred_transitions=preferred,
        main_crops=main_crops,
        unknown_mode=unk_mode,
        adjacent_family_enabled=adjacent_family_enabled,
        adjacency_pairs=adjacency_pairs_idx,
        crop_family_map=crop_family_map,
    )

    # 最適化実行
    high_precision = "高精度" in precision_mode
    timeout = 60 if high_precision else 10

    planner = RotationPlannerORTools(fields, past_years, future_years, crops, constraints)
    plan, score, errors = planner.solve(timeout_seconds=timeout, high_precision=high_precision,
                                        district_grouping=district_grouping)

    # 結果生成
    field_df, summary_df = generate_result_tables(fields, past_years, future_years, plan, crops)

    # CSV出力
    csv_content = generate_csv_content(field_df)
    csv_path = "/tmp/輪作計画.csv"
    with open(csv_path, 'w', encoding='utf-8-sig') as f:
        f.write(csv_content)

    # メッセージ
    message = f"✅ 計画生成完了 (スコア: {score:.1f})\n"
    message += f"・過去{len(past_years)}年 + 将来{len(future_years)}年の計画\n"
    message += f"・ほ場数: {len(fields)}\n"

    if errors:
        message += "\n⚠️ 警告/違反:\n"
        for e in errors[:10]:
            message += f"  - {e}\n"
        if len(errors) > 10:
            message += f"  ... 他{len(errors)-10}件\n"

    # 感度分析
    message += "\n"
    try:
        sensitivity_results = run_sensitivity_analysis(
            fields, past_years, future_years, crops, constraints, score,
            timeout_seconds=1, max_tests=5
        )
        for line in sensitivity_results:
            message += f"{line}\n"
    except Exception as e:
        message += f"📊 ボトルネック分析: 実行できませんでした ({e})\n"

    return field_df, summary_df, csv_path, message


# =============================================================================
# PDF出力
# =============================================================================

def generate_pdf_from_dataframe(field_df, summary_df, title: str = "輪作計画") -> str:
    """
    輪作計画のPDFを生成

    Args:
        field_df: ほ場×年の計画DataFrame
        summary_df: 年別作物面積のサマリーDataFrame
        title: PDFタイトル

    Returns:
        生成したPDFファイルのパス
    """
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from datetime import datetime
    import os

    # 日本語フォント登録（システムフォントを探す）
    font_paths = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf",
        "/usr/share/fonts/truetype/ipafont/ipag.ttf",
        "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
        # macOS
        "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
    ]

    font_name = "Helvetica"  # フォールバック
    for font_path in font_paths:
        if os.path.exists(font_path):
            try:
                pdfmetrics.registerFont(TTFont('JapaneseFont', font_path))
                font_name = 'JapaneseFont'
                break
            except Exception:
                continue

    pdf_path = "/tmp/輪作計画.pdf"
    doc = SimpleDocTemplate(
        pdf_path,
        pagesize=landscape(A4),
        rightMargin=10*mm,
        leftMargin=10*mm,
        topMargin=15*mm,
        bottomMargin=15*mm
    )

    elements = []

    # スタイル
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'JapaneseTitle',
        parent=styles['Heading1'],
        fontName=font_name,
        fontSize=16,
        spaceAfter=10*mm
    )
    subtitle_style = ParagraphStyle(
        'JapaneseSubtitle',
        parent=styles['Heading2'],
        fontName=font_name,
        fontSize=12,
        spaceAfter=5*mm
    )
    normal_style = ParagraphStyle(
        'JapaneseNormal',
        parent=styles['Normal'],
        fontName=font_name,
        fontSize=8
    )

    # タイトル
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    elements.append(Paragraph(f"{title}", title_style))
    elements.append(Paragraph(f"出力日時: {now}", normal_style))
    elements.append(Spacer(1, 5*mm))

    # ほ場×年 計画表
    if field_df is not None and not field_df.empty:
        elements.append(Paragraph("■ ほ場×年 計画表", subtitle_style))

        # DataFrameをテーブルデータに変換
        table_data = [list(field_df.columns)]
        for _, row in field_df.iterrows():
            table_data.append([str(v) if v is not None else "" for v in row.values])

        # 列幅を計算（横長なので均等分割）
        num_cols = len(field_df.columns)
        available_width = landscape(A4)[0] - 20*mm
        col_width = available_width / num_cols

        table = Table(table_data, colWidths=[col_width] * num_cols)
        table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), font_name),
            ('FONTSIZE', (0, 0), (-1, -1), 7),
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.Color(0.95, 0.95, 0.95)]),
        ]))
        elements.append(table)
        elements.append(Spacer(1, 10*mm))

    # 年別作物面積サマリー
    if summary_df is not None and not summary_df.empty:
        elements.append(Paragraph("■ 年別 作物面積(ha)", subtitle_style))

        table_data = [list(summary_df.columns)]
        for _, row in summary_df.iterrows():
            table_data.append([str(v) if v is not None else "" for v in row.values])

        num_cols = len(summary_df.columns)
        col_width = min(25*mm, available_width / num_cols)

        table = Table(table_data, colWidths=[col_width] * num_cols)
        table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), font_name),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('BACKGROUND', (0, 0), (-1, 0), colors.darkblue),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.Color(0.9, 0.95, 1.0)]),
        ]))
        elements.append(table)

    doc.build(elements)
    return pdf_path
