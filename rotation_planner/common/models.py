"""
データモデル定義 - 型ヒント・データクラス

使用方法:
    from rotation_planner.common.models import User, Field, RotationPlan

    # 型ヒントとして使用
    def get_user(user_id: int) -> User:
        ...

    # データクラスとして使用
    user = User(id=1, username="tanaka", role="farmer", ...)
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


# =============================================================================
# ロール定義
# =============================================================================

class Role(Enum):
    """ユーザーロール"""
    ADMIN = "admin"
    JA_STAFF = "ja_staff"
    FARMER = "farmer"


# =============================================================================
# ユーザー
# =============================================================================

@dataclass
class User:
    """ユーザー情報"""
    id: int
    username: str
    role: str  # admin, ja_staff, farmer
    display_name: str
    org_id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @property
    def is_admin(self) -> bool:
        """管理者かどうか"""
        return self.role == Role.ADMIN.value

    @property
    def is_ja_staff(self) -> bool:
        """JA職員かどうか"""
        return self.role == Role.JA_STAFF.value

    @property
    def is_farmer(self) -> bool:
        """農家かどうか"""
        return self.role == Role.FARMER.value

    @property
    def can_access_all_data(self) -> bool:
        """全データにアクセス可能か（管理者またはJA職員）"""
        return self.role in (Role.ADMIN.value, Role.JA_STAFF.value)


# =============================================================================
# ほ場
# =============================================================================

@dataclass
class Field:
    """ほ場情報"""
    id: int
    user_id: int
    field_code: str
    name: str
    district: Optional[str] = None
    area_ha: float = 0.0
    beet_forbidden: bool = False
    coordinates_json: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @property
    def area_a(self) -> float:
        """面積（アール）"""
        return self.area_ha * 100

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Field":
        """辞書からFieldオブジェクトを作成"""
        return cls(
            id=data.get("id", 0),
            user_id=data.get("user_id", 0),
            field_code=data.get("field_code", ""),
            name=data.get("name", ""),
            district=data.get("district"),
            area_ha=data.get("area_ha", 0.0),
            beet_forbidden=bool(data.get("beet_forbidden", False)),
            coordinates_json=data.get("coordinates_json"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )

    def to_dict(self) -> Dict[str, Any]:
        """辞書に変換"""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "field_code": self.field_code,
            "name": self.name,
            "district": self.district,
            "area_ha": self.area_ha,
            "area_a": self.area_a,
            "beet_forbidden": self.beet_forbidden,
            "coordinates_json": self.coordinates_json,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


# =============================================================================
# 作付履歴
# =============================================================================

@dataclass
class CropHistory:
    """作付履歴"""
    id: int
    field_id: int
    year: int
    crop: str
    is_inferred: bool = False
    created_at: Optional[datetime] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CropHistory":
        """辞書からCropHistoryオブジェクトを作成"""
        return cls(
            id=data.get("id", 0),
            field_id=data.get("field_id", 0),
            year=data.get("year", 0),
            crop=data.get("crop", ""),
            is_inferred=bool(data.get("is_inferred", False)),
            created_at=data.get("created_at"),
        )


# =============================================================================
# 輪作計画
# =============================================================================

@dataclass
class PlanDetail:
    """輪作計画詳細（ほ場×年の作付）"""
    id: int
    plan_id: int
    field_id: int
    year: int
    crop: str
    field_code: Optional[str] = None
    field_name: Optional[str] = None
    district: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PlanDetail":
        """辞書からPlanDetailオブジェクトを作成"""
        return cls(
            id=data.get("id", 0),
            plan_id=data.get("plan_id", 0),
            field_id=data.get("field_id", 0),
            year=data.get("year", 0),
            crop=data.get("crop", ""),
            field_code=data.get("field_code"),
            field_name=data.get("field_name"),
            district=data.get("district"),
        )


@dataclass
class RotationPlan:
    """輪作計画"""
    id: int
    user_id: int
    name: str
    start_year: int
    end_year: int
    constraints_json: Optional[str] = None
    metadata_json: Optional[str] = None
    details: List[PlanDetail] = field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @property
    def year_range(self) -> range:
        """計画年度の範囲"""
        return range(self.start_year, self.end_year + 1)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RotationPlan":
        """辞書からRotationPlanオブジェクトを作成"""
        details = [
            PlanDetail.from_dict(d) for d in data.get("details", [])
        ]
        return cls(
            id=data.get("id", 0),
            user_id=data.get("user_id", 0),
            name=data.get("name", ""),
            start_year=data.get("start_year", 0),
            end_year=data.get("end_year", 0),
            constraints_json=data.get("constraints_json"),
            metadata_json=data.get("metadata_json"),
            details=details,
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )

    def to_dict(self) -> Dict[str, Any]:
        """辞書に変換"""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "name": self.name,
            "start_year": self.start_year,
            "end_year": self.end_year,
            "constraints_json": self.constraints_json,
            "metadata_json": self.metadata_json,
            "details": [
                {
                    "id": d.id,
                    "plan_id": d.plan_id,
                    "field_id": d.field_id,
                    "year": d.year,
                    "crop": d.crop,
                    "field_code": d.field_code,
                    "field_name": d.field_name,
                    "district": d.district,
                }
                for d in self.details
            ],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


# =============================================================================
# 農薬関連
# =============================================================================

@dataclass
class PesticideMaster:
    """防除マスタ"""
    id: int
    org_id: int
    crop: str
    month: int
    target: str
    pesticide_name: str
    dilution_rate: Optional[float] = None
    amount_per_10a: float = 0.0
    unit: str = "L"
    notes: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PesticideMaster":
        """辞書からPesticideMasterオブジェクトを作成"""
        return cls(
            id=data.get("id", 0),
            org_id=data.get("org_id", 0),
            crop=data.get("crop", ""),
            month=data.get("month", 0),
            target=data.get("target", ""),
            pesticide_name=data.get("pesticide_name", ""),
            dilution_rate=data.get("dilution_rate"),
            amount_per_10a=data.get("amount_per_10a", 0.0),
            unit=data.get("unit", "L"),
            notes=data.get("notes"),
        )


@dataclass
class PesticideOrder:
    """農薬発注"""
    id: int
    user_id: int
    year: int
    pesticide_name: str
    total_amount: float
    unit: str
    status: str = "draft"  # draft, submitted, approved
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# =============================================================================
# ほ場登録・面積集計関連
# =============================================================================

class LandCategory(Enum):
    """地目"""
    FIELD = "畑"
    CONVERTED = "畑地化済"
    PADDY = "水田"
    UNKNOWN = "不明"

    @property
    def display_name(self) -> str:
        return self.value


@dataclass
class PaddyPolygon:
    """水田ポリゴン"""
    id: int
    field_id: int
    geometry: str  # GeoJSON文字列
    area_ha: float
    is_converted: bool
    conversion_start_year: Optional[int]  # NULL許容
    source: str  # 'maff' / 'kml' / 'manual'
    notes: Optional[str]
    created_at: str
    updated_at: str

    @property
    def land_category(self) -> LandCategory:
        """畑地化フラグに基づく地目"""
        return LandCategory.CONVERTED if self.is_converted else LandCategory.PADDY

    @property
    def subsidy_remaining_years(self) -> Optional[int]:
        """畑地化補助金の残り年数（5年間）。開始年不明ならNone"""
        if not self.is_converted or self.conversion_start_year is None:
            return None
        import datetime
        current_year = datetime.date.today().year
        elapsed = current_year - self.conversion_start_year
        remaining = 5 - elapsed
        return max(0, remaining)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "PaddyPolygon":
        """辞書からPaddyPolygonオブジェクトを作成"""
        return cls(
            id=d["id"],
            field_id=d["field_id"],
            geometry=d["geometry"],
            area_ha=d["area_ha"],
            is_converted=bool(d["is_converted"]),
            conversion_start_year=d.get("conversion_start_year"),
            source=d.get("source", "manual"),
            notes=d.get("notes"),
            created_at=d.get("created_at", ""),
            updated_at=d.get("updated_at", ""),
        )


@dataclass
class CropPolygon:
    """作物ポリゴン"""
    id: int
    field_id: int
    year: int
    crop_name: str
    geometry: str  # GeoJSON文字列
    area_ha: float
    notes: Optional[str]
    created_at: str
    updated_at: str

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "CropPolygon":
        """辞書からCropPolygonオブジェクトを作成"""
        return cls(
            id=d["id"],
            field_id=d["field_id"],
            year=d["year"],
            crop_name=d["crop_name"],
            geometry=d["geometry"],
            area_ha=d["area_ha"],
            notes=d.get("notes"),
            created_at=d.get("created_at", ""),
            updated_at=d.get("updated_at", ""),
        )



@dataclass
class AggregationRow:
    """集計表の1行（1作物の地目別面積）"""
    crop_name: str
    field_area_ha: float  # 畑
    converted_areas: Dict[Any, float]  # {year_or_unknown: area_ha} 例: {2022: 1.0, 'unknown': 0.3}
    paddy_area_ha: float  # 水田

    @property
    def total_area(self) -> float:
        """合計面積"""
        return self.field_area_ha + sum(self.converted_areas.values()) + self.paddy_area_ha
