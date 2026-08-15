# -*- coding: utf-8 -*-
"""
湖南省新能源投资项目事前拦截与测算报告系统（融合版）
适用于：风电、光伏、用户侧储能、绿电直连等项目事前合规校验与投资测算
"""

import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from datetime import datetime
import re

# ============================================================
# 页面配置
# ============================================================

st.set_page_config(
    page_title="湖南省新能源项目合规风险自检与测算系统",
    layout="wide",
    initial_sidebar_state="expanded"
)

PROJECT_TYPES = ["光伏", "风电", "用户侧储能", "绿电直连"]

VOLTAGE_OPTIONS = [
    "10(6) kV",
    "35 kV",
    "110 kV",
    "220 kV",
    ">220 kV"
]

VOLTAGE_MAP = {
    "10(6) kV": 10,
    "35 kV": 35,
    "110 kV": 110,
    "220 kV": 220,
    ">220 kV": 330
}

POLICY_CAPTION = (
    "政策依据参考：《湖南省分布式光伏发电开发建设管理实施细则》（湘发改能源规〔2025〕843号）、"
    "《湖南省有序推动绿电直连发展实施方案》（湘发改能源〔2025〕853号）、"
    "《湖南省深化新能源上网电价市场化改革促进新能源高质量发展实施方案》（湘发改价调〔2025〕663号）"
    "及湖南省发改委、能源局、国网湖南电力相关并网消纳、现货交易、可开放容量管理要求。"
)


# ============================================================
# 基础工具函数
# ============================================================

def parse_location(text):
    """
    简单解析项目坐标或地址。
    支持示例：
      - 112.98, 28.19 (长沙市岳麓区)
      - 28.2° N, 112.9° E
      - 北纬28.2，东经112.9
    如无法解析，返回默认长沙坐标，并提示需接入真实地理编码服务。
    """
    text = (text or "").strip()
    if not text:
        return None, None, False

    # 优先解析 N/E 格式
    m_lat = re.search(r"([-+]?\d+(?:\.\d+)?)\s*(?:°|度)?\s*N", text, re.IGNORECASE)
    m_lon = re.search(r"([-+]?\d+(?:\.\d+)?)\s*(?:°|度)?\s*E", text, re.IGNORECASE)

    if m_lat and m_lon:
        return float(m_lat.group(1)), float(m_lon.group(1)), True

    # 解析中文经纬度
    m_lat_cn = re.search(r"北纬\s*([-+]?\d+(?:\.\d+)?)", text)
    m_lon_cn = re.search(r"东经\s*([-+]?\d+(?:\.\d+)?)", text)

    if m_lat_cn and m_lon_cn:
        return float(m_lat_cn.group(1)), float(m_lon_cn.group(1)), True

    # 提取所有数字
    nums = re.findall(r"[-+]?\d+(?:\.\d+)?", text)
    floats = [float(x) for x in nums]

    if len(floats) >= 2:
        a, b = floats[0], floats[1]

        # 中国大陆大致范围：经度约 73-136，纬度约 15-55
        if 73 <= a <= 136 and 15 <= b <= 55:
            lon, lat = a, b
        elif 15 <= a <= 55 and 73 <= b <= 136:
            lat, lon = a, b
        elif abs(a) <= 90 and abs(b) > 90:
            lat, lon = a, b
        elif abs(b) <= 90 and abs(a) > 90:
            lon, lat = a, b
        else:
            # 默认按“经度,纬度”处理
            lon, lat = a, b

        return lat, lon, True

    return None, None, False


def recommend_voltage(capacity, project_type):
    """
    根据容量和项目类型推荐接入电压等级。
    实际项目仍应以电网企业接入系统方案审查为准。
    """
    if project_type == "用户侧储能" and capacity <= 6:
        return "10(6) kV"

    if capacity <= 6:
        return "10(6) kV"
    elif capacity <= 20:
        return "35 kV"
    elif capacity <= 50:
        return "110 kV"
    else:
        return "220 kV"


def get_default_hours(project_type):
    """
    获取默认首年等效利用小时数，仅作为测算示例。
    实际应按资源评估、发电量模拟、储能运行策略等确定。
    """
    if project_type == "风电":
        return 2158
    elif project_type == "光伏":
        return 975
    elif project_type == "绿电直连":
        return 975
    else:
        return 0


def get_default_capex(project_type):
    """
    获取默认单位投资，仅作为测算示例。
    单位：万元/MW。
    """
    if project_type == "光伏":
        return 380.0
    elif project_type == "风电":
        return 620.0
    elif project_type == "用户侧储能":
        return 2200.0
    elif project_type == "绿电直连":
        return 420.0
    else:
        return 400.0


# ============================================================
# 合规校验函数
# ============================================================

def evaluate_land(project_type, land_use, has_certificate, self_use_ratio):
    """
    用地性质红线校验。
    真实系统应对接湖南省自然资源厅、永久基本农田、生态保护红线、一级林地等 GIS 图层。
    """
    if land_use == "红线外":
        return {
            "status": "通过",
            "message": "项目用地初步判断位于红线外，需进一步取得用地预审与规划选址意见。",
            "pass": True
        }

    if land_use == "红线内需审批":
        if has_certificate:
            return {
                "status": "通过",
                "message": "项目涉及红线内需审批，但已取得审批/权属证明，建议留存自然资源局、林业局等部门意见。",
                "pass": True
            }
        else:
            return {
                "status": "拦截",
                "message": "项目涉及红线内需审批，但未提供审批/权属证明，存在用地合规风险，不建议继续推进。",
                "pass": False
            }

    if land_use == "红线内（自发自用优先）":
        if project_type in ["用户侧储能", "绿电直连"]:
            if self_use_ratio >= 80 or has_certificate:
                return {
                    "status": "通过",
                    "message": "红线内自发自用/绿电直连模式初步可行，建议确保自发自用比例、权属证明及独立计量条件。",
                    "pass": True
                }
            else:
                return {
                    "status": "拦截",
                    "message": "红线内自发自用/绿电直连模式下，自发自用比例不足或权属证明不完整，存在高合规风险。",
                    "pass": False
                }

        if project_type == "光伏":
            if self_use_ratio >= 80:
                return {
                    "status": "通过",
                    "message": "分布式光伏红线内自发自用初步可行，建议确保自发自用比例≥80%，并满足独立计量要求。",
                    "pass": True
                }
            elif has_certificate:
                return {
                    "status": "警告",
                    "message": "分布式光伏涉及红线内，但已取得部分权属证明。需进一步确认自发自用比例及并网方案。",
                    "pass": True
                }
            else:
                return {
                    "status": "拦截",
                    "message": "分布式光伏涉及红线内且自发自用比例不足，存在用地合规风险。",
                    "pass": False
                }

        return {
            "status": "拦截",
            "message": "集中式风电/光伏原则上不得占用红线内区域，建议调整选址或重新开展用地合规论证。",
            "pass": False
        }

    return {
        "status": "警告",
        "message": "用地性质未明确，需补充自然资源、林业、水利等部门核查意见。",
        "pass": True
    }


def evaluate_grid(consumption_zone, lat, lon, capacity, project_type):
    """
    电网消纳红区校验。
    真实系统应接入国网湖南电力可开放容量、变电站主变容量、台区承载力、消纳预警分区等数据。
    """
    if consumption_zone == "可开放容量区域":
        if project_type in ["光伏", "风电"] and capacity > 100:
            return {
                "status": "警告",
                "message": "项目位于可开放容量区域，但装机规模较大，需开展接入系统方案及消纳能力专项评估。",
                "pass": True
            }
        return {
            "status": "通过",
            "message": "项目初步位于电网可开放容量区域，仍需以国网湖南电力营销2.0系统可开放容量评估为准。",
            "pass": True
        }

    if consumption_zone == "黄/红预警区":
        if project_type in ["光伏", "风电"] and capacity > 20:
            return {
                "status": "拦截",
                "message": "项目位于电网消纳黄/红预警区，且装机规模超过20MW，原则上需取得可开放容量评估、储能配置或调峰能力证明后方可推进并网。",
                "pass": False
            }
        return {
            "status": "警告",
            "message": "项目位于电网消纳黄/红预警区，需配建储能、参与调峰或优化为自发自用/绿电直连模式。",
            "pass": True
        }

    # 消纳区未知时，按坐标进行模拟判断
    if lon is not None and lon < 111.0:
        return {
            "status": "拦截",
            "message": "模拟判断：项目可能位于湘西电网消纳红区，变电站主变容量接近满载，建议暂停新增并网审批并优先开展可开放容量核查。",
            "pass": False
        }

    if project_type in ["光伏", "风电"] and capacity > 20:
        return {
            "status": "警告",
            "message": "项目消纳条件初步判断偏紧，建议开展接入系统方案审查、可开放容量评估及储能/调峰能力配置。",
            "pass": True
        }

    return {
        "status": "通过",
        "message": "未识别到明显消纳红区，但仍需以国网湖南电力可开放容量评估和接入系统方案审查为准。",
        "pass": True
    }


def evaluate_voltage(selected_voltage, recommended_voltage, capacity, project_type):
    """
    接入电压等级条件校验。
    """
    selected_kv = VOLTAGE_MAP.get(selected_voltage, 0)
    recommended_kv = VOLTAGE_MAP.get(recommended_voltage, 0)

    if selected_kv > 220:
        return {
            "status": "拦截",
            "message": "接入电压等级超过220kV，需省级能源局、国家能源局湖南监管办及电网企业专项评估，事前拦截风险较高。",
            "pass": False
        }

    if project_type == "绿电直连" and selected_kv > 220:
        return {
            "status": "拦截",
            "message": "绿电直连项目接入电压等级不应超过220kV，需重新论证接入方案。",
            "pass": False
        }

    if selected_kv > recommended_kv and capacity <= 20 and selected_kv >= 220:
        return {
            "status": "警告",
            "message": f"接入电压等级偏高。系统推荐接入电压为{recommended_voltage}，当前选择为{selected_voltage}，需电网企业确认技术经济性。",
            "pass": True
        }

    if selected_kv > recommended_kv:
        return {
            "status": "警告",
            "message": f"接入电压等级与容量初步匹配性偏弱。系统推荐接入电压为{recommended_voltage}，当前选择为{selected_voltage}，需以接入系统方案审查为准。",
            "pass": True
        }

    return {
        "status": "通过",
        "message": f"接入电压等级初步匹配，推荐接入电压为{recommended_voltage}。",
        "pass": True
    }


def evaluate_green_direct(project_type, self_use_ratio, selected_voltage):
    """
    绿电直连专项校验。
    """
    if project_type != "绿电直连":
        return {
            "status": "不适用",
            "message": "当前项目非绿电直连项目。",
            "pass": True
        }

    selected_kv = VOLTAGE_MAP.get(selected_voltage, 0)

    if selected_kv > 220:
        return {
            "status": "拦截",
            "message": "绿电直连项目接入电压等级不应超过220kV。",
            "pass": False
        }

    if self_use_ratio < 60:
        return {
            "status": "拦截",
            "message": "绿电直连项目自身新能源消纳比例偏低，建议按‘以荷定源’原则重新匹配负荷与电源规模。",
            "pass": False
        }

    if self_use_ratio < 80:
        return {
            "status": "警告",
            "message": "绿电直连项目需控制年上网电量比例，原则上余电上网不宜超过总发电量20%。",
            "pass": True
        }

    return {
        "status": "通过",
        "message": "绿电直连项目初步满足自发自用比例、接入电压等要求，需进一步签订多年期购电协议并纳入电网企业一站式服务流程。",
        "pass": True
    }


def build_risks(
    project_type,
    capacity,
    market_participation,
    self_use_ratio,
    land_res,
    grid_res,
    voltage_res,
    green_res
):
    """
    自动追加合规风险标注。
    """
    risks = []

    if land_res["status"] == "拦截":
        risks.append(f"🔴 **高风险｜用地红线**：{land_res['message']}")
    elif land_res["status"] == "警告":
        risks.append(f"🟡 **中风险｜用地合规**：{land_res['message']}")

    if grid_res["status"] == "拦截":
        risks.append(f"🔴 **高风险｜电网消纳红区**：{grid_res['message']}")
    elif grid_res["status"] == "警告":
        risks.append(f"🟡 **中风险｜电网消纳预警**：{grid_res['message']}")

    if voltage_res["status"] == "拦截":
        risks.append(f"🔴 **高风险｜接入电压等级**：{voltage_res['message']}")
    elif voltage_res["status"] == "警告":
        risks.append(f"🟡 **中风险｜接入电压匹配**：{voltage_res['message']}")

    if green_res["status"] == "拦截":
        risks.append(f"🔴 **高风险｜绿电直连**：{green_res['message']}")
    elif green_res["status"] == "警告":
        risks.append(f"🟡 **中风险｜绿电直连**：{green_res['message']}")

    if project_type == "用户侧储能" and capacity > 1.0:
        risks.append(
            "🟡 **中风险｜用户侧储能**：储能规模可能超过用户实际负荷，需开展负荷匹配分析，并按GB/T 43526等要求配置独立计量、安全消防及并网/非并网运行方案。"
        )

    if project_type == "绿电直连" and self_use_ratio < 80:
        risks.append(
            "🟡 **中风险｜绿电直连余电控制**：绿电直连项目应按‘以荷定源’原则配置，年上网电量原则上不宜超过总发电量20%。"
        )

    if not market_participation:
        risks.append(
            "🟢 **低风险｜市场参与**：项目可申请不参与现货/竞价，但仍需通过国网湖南电力营销2.0系统完成备案，并满足属地并网审批要求。"
        )

    risks.append(
        "📌 **并网审批与现货规则限制**：本报告所有测算结果均受限于属地并网审批进度、国网湖南电力营销2.0系统认定的并网容量与并网时点；"
        "增量新能源项目原则上需参与年度竞价或现货市场交易，机制电量、机制电价及结算收益受湖南现货规则、节点电价、消纳责任权重调整影响。"
    )

    return risks


# ============================================================
# 财务测算函数
# ============================================================

def calculate_finance(
    project_type,
    capacity,
    hours,
    capex_wan_per_mw,
    mechanism_price,
    market_price,
    self_use_price,
    self_use_ratio,
    peak_valley_spread,
    storage_duration,
    cycle_days=330,
    roundtrip_eff=0.87
):
    """
    简化财务测算模型。
    未考虑贷款、税费、衰减、运维精细化策略、土地租金、配储成本拆分等。
    """
    capex_wan = capacity * capex_wan_per_mw

    # 用户侧储能单独测算
    if project_type == "用户侧储能":
        annual_discharge_kwh = capacity * storage_duration * 1000 * cycle_days
        annual_revenue_yuan = annual_discharge_kwh * peak_valley_spread * roundtrip_eff
        annual_revenue_wan = annual_revenue_yuan / 10000

        opex_wan = capex_wan * 0.02
        net_income_wan = annual_revenue_wan - opex_wan

        payback = capex_wan / net_income_wan if net_income_wan > 0 else None
        simple_return = net_income_wan / capex_wan * 100 if capex_wan > 0 and net_income_wan > 0 else None

        return {
            "capex_wan": capex_wan,
            "annual_energy_kwh": annual_discharge_kwh,
            "annual_energy_display": f"{annual_discharge_kwh / 10000:,.0f} 万kWh/年放电量",
            "annual_revenue_wan": annual_revenue_wan,
            "opex_wan": opex_wan,
            "net_income_wan": net_income_wan,
            "payback_years": payback,
            "simple_return_pct": simple_return
        }

    # 风电、光伏、绿电直连
    annual_generation_kwh = capacity * hours * 1000

    if project_type == "绿电直连":
        self_ratio = max(0.0, min(1.0, self_use_ratio / 100.0))
        self_kwh = annual_generation_kwh * self_ratio
        grid_kwh = annual_generation_kwh * min(1.0 - self_ratio, 0.20)
        curtailed_kwh = max(annual_generation_kwh - self_kwh - grid_kwh, 0)

        annual_revenue_yuan = self_kwh * self_use_price + grid_kwh * market_price
        annual_revenue_wan = annual_revenue_yuan / 10000

        opex_wan = capex_wan * 0.02
        net_income_wan = annual_revenue_wan - opex_wan

        payback = capex_wan / net_income_wan if net_income_wan > 0 else None
        simple_return = net_income_wan / capex_wan * 100 if capex_wan > 0 and net_income_wan > 0 else None

        return {
            "capex_wan": capex_wan,
            "annual_energy_kwh": annual_generation_kwh,
            "annual_energy_display": f"{annual_generation_kwh / 10000:,.0f} 万kWh/年发电量",
            "annual_revenue_wan": annual_revenue_wan,
            "opex_wan": opex_wan,
            "net_income_wan": net_income_wan,
            "payback_years": payback,
            "simple_return_pct": simple_return,
            "self_kwh": self_kwh,
            "grid_kwh": grid_kwh,
            "curtailed_kwh": curtailed_kwh
        }

    # 风电、光伏按机制电量+现货电量简化测算
    mechanism_ratio = 0.8
    mechanism_kwh = annual_generation_kwh * mechanism_ratio
    market_kwh = annual_generation_kwh * (1 - mechanism_ratio)

    annual_revenue_yuan = mechanism_kwh * mechanism_price + market_kwh * market_price
    annual_revenue_wan = annual_revenue_yuan / 10000

    opex_rate = 0.015
    opex_wan = capex_wan * opex_rate
    net_income_wan = annual_revenue_wan - opex_wan

    payback = capex_wan / net_income_wan if net_income_wan > 0 else None
    simple_return = net_income_wan / capex_wan * 100 if capex_wan > 0 and net_income_wan > 0 else None

    return {
        "capex_wan": capex_wan,
        "annual_energy_kwh": annual_generation_kwh,
        "annual_energy_display": f"{annual_generation_kwh / 10000:,.0f} 万kWh/年发电量",
        "annual_revenue_wan": annual_revenue_wan,
        "opex_wan": opex_wan,
        "net_income_wan": net_income_wan,
        "payback_years": payback,
        "simple_return_pct": simple_return,
        "mechanism_kwh": mechanism_kwh,
        "market_kwh": market_kwh
    }


# ============================================================
# GIS 地图函数
# ============================================================

def render_gis_map(lat, lon, overall_status, project_type, capacity, address_text):
    """
    渲染GIS核查图。
    当前为演示版：仅显示项目落点及500m核查缓冲。
    真实版应叠加：永久基本农田、生态保护红线、一级林地、电网可开放容量热力图、变电站点位等。
    """
    if overall_status == "通过":
        color = "green"
        popup_text = "初步合规"
    elif overall_status == "警告":
        color = "orange"
        popup_text = "存在预警"
    else:
        color = "red"
        popup_text = "存在拦截项"

    m = folium.Map(location=[lat, lon], zoom_start=12)

    folium.Marker(
        location=[lat, lon],
        popup=(
            f"项目类型：{project_type}<br>"
            f"装机容量：{capacity} MW<br>"
            f"坐标/地址：{address_text}<br>"
            f"核查结果：{popup_text}"
        ),
        tooltip="项目位置"
    ).add_to(m)

    folium.Circle(
        location=[lat, lon],
        radius=500,
        color=color,
        fill=True,
        fill_opacity=0.2,
        tooltip="500m合规核查缓冲区"
    ).add_to(m)

    return m


# ============================================================
# 报告文本生成函数
# ============================================================

def build_markdown_report(
    project_type,
    address_text,
    capacity,
    selected_voltage,
    recommended_voltage,
    land_use,
    consumption_zone,
    self_use_ratio,
    market_participation,
    land_res,
    grid_res,
    voltage_res,
    green_res,
    risks,
    finance
):
    """
    生成可下载的 Markdown 报告。
    如需PDF，可后续接入 reportlab、weasyprint 或浏览器打印PDF。
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    market_text = "参与" if market_participation else "不参与"

    lines = [
        "# 湖南省新能源投资项目事前拦截与测算报告",
        "",
        f"**生成时间**：{now}",
        "",
        "## 一、项目基本信息",
        "",
        f"- 项目类型：{project_type}",
        f"- 项目坐标/地址：{address_text}",
        f"- 装机容量：{capacity} MW",
        f"- 用户选择接入电压等级：{selected_voltage}",
        f"- 系统推荐接入电压等级：{recommended_voltage}",
        f"- 用地性质：{land_use}",
        f"- 电网消纳区域：{consumption_zone}",
        f"- 自发自用比例：{self_use_ratio}%",
        f"- 现货市场/竞价参与：{market_text}",
        "",
        "## 二、合规校验结果",
        "",
        f"- 用地性质红线：{land_res['status']}",
        f"  - {land_res['message']}",
        f"- 电网消纳红区：{grid_res['status']}",
        f"  - {grid_res['message']}",
        f"- 接入电压等级：{voltage_res['status']}",
        f"  - {voltage_res['message']}",
        f"- 绿电直连专项：{green_res['status']}",
        f"  - {green_res['message']}",
        "",
        "## 三、合规风险标注",
        ""
    ]

    for risk in risks:
        lines.append(f"- {risk}")

    lines += [
        "",
        "## 四、投资测算结果（简化版）",
        "",
        f"- 初始投资估算：{finance['capex_wan']:,.0f} 万元",
        f"- 首年电量指标：{finance['annual_energy_display']}",
        f"- 首年收益估算：{finance['annual_revenue_wan']:,.2f} 万元",
        f"- 年运维成本估算：{finance['opex_wan']:,.2f} 万元",
        f"- 年净收益估算：{finance['net_income_wan']:,.2f} 万元",
    ]

    if finance.get("payback_years"):
        lines.append(f"- 静态投资回收期：{finance['payback_years']:.2f} 年")
    else:
        lines.append("- 静态投资回收期：暂无法测算，收益不足或未覆盖投资")

    if finance.get("simple_return_pct"):
        lines.append(f"- 简化年收益率：{finance['simple_return_pct']:.2f}%")
    else:
        lines.append("- 简化年收益率：暂无法测算")

    lines += [
        "",
        "> 说明：以上测算为简化模型，未考虑贷款、税费、衰减率、储能实际充放电策略、现货节点电价波动、限电率、土地租金、配储成本细分、绿证收益等。",
        "> 所有收益测算均受限于属地并网审批进度、国网湖南电力营销2.0系统并网容量认定、湖南现货市场规则及年度竞价结果。",
        "",
        "## 五、合规路径建议",
        "",
        "1. 在签署土地流转/租赁协议前，取得自然资源、林业、水利等部门不涉及生态保护红线、永久基本农田、一级林地、饮用水源保护区等敏感区域的核查意见。",
        "2. 对电网消纳黄区/红区项目，优先开展国网湖南电力可开放容量评估；如不具备上网条件，可论证转为绿电直连、自发自用、用户侧储能或微电网模式。",
        "3. 在EPC合同、投资协议、购电协议中增加因政策调整、现货市场规则变化、并网容量限制、消纳能力变化导致收益波动的风险分担条款。",
        "4. 光伏、风电项目应关注湖南现货市场中午低价/负电价风险；增量项目需重点评估机制电量比例、机制电价、竞价上限及结算规则。",
        "5. 绿电直连项目应坚持‘以荷定源’，确保负荷匹配、自发自用比例、余电上网比例、多年期购电协议及电网企业一站式服务流程落地。",
        "",
        "## 六、政策依据提示",
        "",
        POLICY_CAPTION,
        "",
        "---",
        "",
        "**免责声明**：本报告为政策合规风险自检与投资测算演示，不替代政府部门备案、电网企业接入系统方案审查、用地预审、环评、安评、水保等法定程序。"
    ]

    return "\n".join(lines)


# ============================================================
# 主界面
# ============================================================

def main():
    st.title("🌟 湖南省新能源投资项目事前拦截与测算报告系统")
    st.caption(POLICY_CAPTION)

    with st.sidebar.form("project_form"):
        st.header("📋 项目输入")

        project_type = st.selectbox(
            "项目类型",
            PROJECT_TYPES,
            index=0
        )

        project_location = st.text_input(
            "项目坐标或详细地址",
            value="112.98, 28.19 (长沙市岳麓区)",
            help="支持：经度,纬度；28.2° N, 112.9° E；北纬28.2，东经112.9；或地址文本。正式系统建议接入地理编码服务。"
        )

        capacity = st.number_input(
            "装机容量 (MW)",
            min_value=0.1,
            max_value=1000.0,
            value=10.0,
            step=0.1
        )

        st.markdown("#### ⚡ 接入电压等级")
        use_recommended_voltage = st.checkbox(
            "使用系统推荐接入电压等级",
            value=True
        )

        voltage_option = st.selectbox(
            "手动选择接入电压等级",
            VOLTAGE_OPTIONS,
            index=1,
            disabled=use_recommended_voltage
        )

        st.markdown("#### 🗺️ 用地与消纳条件")

        land_use = st.selectbox(
            "用地性质",
            [
                "红线外",
                "红线内（自发自用优先）",
                "红线内需审批"
            ],
            index=0
        )

        has_certificate = st.checkbox(
            "已取得用地审批/权属证明",
            value=False
        )

        self_use_ratio = st.slider(
            "自发自用比例 (%)",
            min_value=0,
            max_value=100,
            value=80,
            step=5,
            help="用于分布式光伏、用户侧储能、绿电直连等自发自用类项目合规判断。"
        )

        consumption_zone = st.selectbox(
            "电网消纳区域",
            [
                "可开放容量区域",
                "黄/红预警区",
                "未知"
            ],
            index=0
        )

        market_participation = st.checkbox(
            "参与现货市场/竞价",
            value=True
        )

        with st.expander("🧮 高级测算参数"):
            default_hours = get_default_hours(project_type)
            default_capex = get_default_capex(project_type)

            hours = st.number_input(
                "首年等效利用小时数 (h)",
                min_value=0.0,
                max_value=5000.0,
                value=float(default_hours),
                step=10.0,
                key=f"hours_{project_type}",
                help="用户侧储能不使用该参数，系统按储能时长与循环天数测算。"
            )

            capex_wan_per_mw = st.number_input(
                "单位投资 (万元/MW)",
                min_value=0.0,
                max_value=20000.0,
                value=float(default_capex),
                step=10.0,
                key=f"capex_{project_type}",
                help="仅作为简化测算示例。光伏约380万元/MW，风电约620万元/MW，用户侧储能可按功率+储能时长另行测算。"
            )

            mechanism_price = st.number_input(
                "机制电价 (元/kWh)",
                min_value=0.0,
                max_value=1.5,
                value=0.32,
                step=0.01,
                key="mechanism_price"
            )

            market_price = st.number_input(
                "现货/余电电价 (元/kWh)",
                min_value=0.0,
                max_value=1.5,
                value=0.25,
                step=0.01,
                key="market_price"
            )

            self_use_price = st.number_input(
                "自发自用替代电价 (元/kWh)",
                min_value=0.0,
                max_value=2.0,
                value=0.65,
                step=0.01,
                key="self_use_price",
                help="绿电直连或自发自用项目中，自用部分按用户侧替代电价估算。"
            )

            peak_valley_spread = st.number_input(
                "储能峰谷价差 (元/kWh)",
                min_value=0.0,
                max_value=2.0,
                value=0.60,
                step=0.01,
                key="peak_valley_spread"
            )

            storage_duration = st.number_input(
                "储能时长 (h)",
                min_value=0.5,
                max_value=8.0,
                value=2.0,
                step=0.5,
                key="storage_duration"
            )

        submitted = st.form_submit_button("🚀 一键校验并生成报告", type="primary")

    if not submitted:
        st.info("👈 请在左侧输入项目坐标、项目属性、装机容量、用地性质、消纳区域等参数，点击【一键校验并生成报告】。")
        return

    # ------------------------------------------------------------
    # 右侧报告执行区
    # ------------------------------------------------------------

    with st.spinner("正在调用湖南省用地红线、电网消纳、接入电压及政策规则引擎进行核查..."):
        lat, lon, coord_ok = parse_location(project_location)

        if not coord_ok:
            lat, lon = 28.2, 112.9
            st.warning("未能从输入中解析有效坐标，已默认定位到长沙市示例坐标。正式系统建议接入高德/百度/天地图等地理编码服务。")

        recommended_voltage = recommend_voltage(capacity, project_type)
        selected_voltage = recommended_voltage if use_recommended_voltage else voltage_option

        land_res = evaluate_land(project_type, land_use, has_certificate, self_use_ratio)
        grid_res = evaluate_grid(consumption_zone, lat, lon, capacity, project_type)
        voltage_res = evaluate_voltage(selected_voltage, recommended_voltage, capacity, project_type)
        green_res = evaluate_green_direct(project_type, self_use_ratio, selected_voltage)

        results = [land_res, grid_res, voltage_res, green_res]

        if any(item["status"] == "拦截" for item in results):
            overall_status = "拦截"
        elif any(item["status"] == "警告" for item in results):
            overall_status = "警告"
        else:
            overall_status = "通过"

        risks = build_risks(
            project_type=project_type,
            capacity=capacity,
            market_participation=market_participation,
            self_use_ratio=self_use_ratio,
            land_res=land_res,
            grid_res=grid_res,
            voltage_res=voltage_res,
            green_res=green_res
        )

        finance = calculate_finance(
            project_type=project_type,
            capacity=capacity,
            hours=hours,
            capex_wan_per_mw=capex_wan_per_mw,
            mechanism_price=mechanism_price,
            market_price=market_price,
            self_use_price=self_use_price,
            self_use_ratio=self_use_ratio,
            peak_valley_spread=peak_valley_spread,
            storage_duration=storage_duration
        )

    # ------------------------------------------------------------
    # 总体结论
    # ------------------------------------------------------------

    st.header("📊 实时校验结果与完整测算报告")

    if overall_status == "通过":
        st.success("✅ 初步合规校验通过。项目可进入备案、接入系统方案、用地预审及并网申请等后续流程，但仍需以属地主管部门和电网企业正式意见为准。")
    elif overall_status == "警告":
        st.warning("⚠️ 项目存在合规预警项。建议在完成整改、补充评估或取得专项意见前，谨慎签署投资协议、土地协议及EPC合同。")
    else:
        st.error("❌ 项目触发事前拦截项。建议暂停推进当前选址/接入方案，优先调整用地选址、消纳模式、接入电压或项目开发模式。")

    # ------------------------------------------------------------
    # 校验指标卡
    # ------------------------------------------------------------

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric(
            "用地性质红线",
            land_res["status"],
            delta="合规" if land_res["pass"] else "风险"
        )

    with col2:
        st.metric(
            "电网消纳红区",
            grid_res["status"],
            delta="可继续" if grid_res["pass"] else "拦截"
        )

    with col3:
        st.metric(
            "接入电压等级",
            voltage_res["status"],
            delta=f"推荐：{recommended_voltage}"
        )

    with col4:
        st.metric(
            "绿电直连专项",
            green_res["status"],
            delta="适用" if project_type == "绿电直连" else "非绿电直连"
        )

    # ------------------------------------------------------------
    # 参数明细
    # ------------------------------------------------------------

    st.subheader("📝 参数明细")

    param_df = pd.DataFrame(
        {
            "参数指标": [
                "项目类型",
                "项目坐标/地址",
                "装机容量 (MW)",
                "用户选择接入电压等级",
                "系统推荐接入电压等级",
                "用地性质",
                "是否取得审批/权属证明",
                "自发自用比例 (%)",
                "电网消纳区域",
                "现货市场/竞价参与",
                "首年等效利用小时数 (h)",
                "单位投资 (万元/MW)"
            ],
            "输入值": [
                project_type,
                project_location,
                f"{capacity} MW",
                selected_voltage,
                recommended_voltage,
                land_use,
                "是" if has_certificate else "否",
                self_use_ratio,
                consumption_zone,
                "参与" if market_participation else "不参与",
                hours if project_type != "用户侧储能" else "按储能策略测算",
                capex_wan_per_mw
            ]
        }
    )

    st.table(param_df)

    # ------------------------------------------------------------
    # 合规风险标注
    # ------------------------------------------------------------

    st.subheader("🛡️ 合规风险标注（自动追加）")

    for risk in risks:
        st.markdown(risk)

    # ------------------------------------------------------------
    # GIS核查图
    # ------------------------------------------------------------

    st.subheader("🗺️ GIS核查图")

    st.info(
        "当前GIS核查图为演示版，已显示项目落点及500m核查缓冲。"
        "正式版应叠加湖南省永久基本农田、生态保护红线、一级林地、自然保护区、饮用水源保护区、"
        "国网湖南电力可开放容量热力图、变电站布点、消纳红黄绿区等图层。"
    )

    gis_map = render_gis_map(
        lat=lat,
        lon=lon,
        overall_status=overall_status,
        project_type=project_type,
        capacity=capacity,
        address_text=project_location
    )

    st_folium(gis_map, width=850, height=450)

    # ------------------------------------------------------------
    # 投资测算
    # ------------------------------------------------------------

    st.subheader("📈 投资测算报告（简化版）")

    fin_col1, fin_col2, fin_col3, fin_col4 = st.columns(4)

    with fin_col1:
        st.metric(
            "初始投资估算",
            f"{finance['capex_wan']:,.0f} 万元"
        )

    with fin_col2:
        st.metric(
            "首年电量指标",
            finance["annual_energy_display"]
        )

    with fin_col3:
        st.metric(
            "首年收益估算",
            f"{finance['annual_revenue_wan']:,.2f} 万元"
        )

    with fin_col4:
        if finance.get("payback_years"):
            st.metric(
                "静态投资回收期",
                f"{finance['payback_years']:.2f} 年"
            )
        else:
            st.metric(
                "静态投资回收期",
                "暂无法测算"
            )

    st.write(
        f"**年运维成本估算**：{finance['opex_wan']:,.2f} 万元 | "
        f"**年净收益估算**：{finance['net_income_wan']:,.2f} 万元 | "
        f"**简化年收益率**：{finance.get('simple_return_pct', 0):.2f}%"
    )

    if project_type == "光伏" or project_type == "风电":
        st.info(
            "计价规则提示：增量新能源项目可参考‘机制电量+市场化电量’模型。"
            "本模型默认80%电量享受机制电价，20%电量参与现货/市场化交易，实际比例以湖南省最新竞价文件与并网协议为准。"
        )

    if project_type == "绿电直连":
        st.info(
            "绿电直连提示：项目应坚持‘以荷定源’，自身新能源消纳比例、占总用电量比例、余电上网比例应满足湖南省绿电直连政策要求；"
            "建议签订多年期购电协议，并纳入电网企业‘一站式’服务流程。"
        )

    if project_type == "用户侧储能":
        st.info(
            "用户侧储能提示：本模型按峰谷套利进行简化测算，实际收益还应考虑需量管理、辅助服务、应急备用、充放电策略、"
            "安全运维成本、电池衰减、循环寿命及属地并网/非并网运行要求。"
        )

    st.warning(
        "⚠️ 测算结果受限提示：本部分收益、回收期、收益率均受限于属地并网审批进度、国网湖南电力营销2.0系统认定的并网容量与并网时点；"
        "同时受湖南现货市场规则、年度竞价规模、机制电量比例、机制电价、节点电价波动及消纳责任权重调整影响。"
    )

    # ------------------------------------------------------------
    # 合规路径建议
    # ------------------------------------------------------------

    st.subheader("💡 合规路径建议")

    if overall_status == "通过":
        st.success(
            "**立即可行路径建议**：\n\n"
            "1. 对接属地发改/能源主管部门开展项目备案；\n"
            "2. 通过国网湖南电力营销2.0系统提交并网申请与可开放容量核查；\n"
            "3. 办理用地预审、规划、环评、安评等必要手续；\n"
            "4. 按湖南现货市场规则参与竞价或签订市场化购电协议；\n"
            "5. 在投资协议中预留政策调整与并网延期风险条款。"
        )
    elif overall_status == "警告":
        st.warning(
            "**需整改后推进路径建议**：\n\n"
            "1. 补充自然资源局、林业局等部门用地合规证明；\n"
            "2. 申请国网湖南电力可开放容量评估或接入系统方案审查；\n"
            "3. 如处于消纳预警区，考虑配建储能、租赁储能、参与调峰或转为自发自用/绿电直连模式；\n"
            "4. 重新复核接入电压等级、并网容量及计量方案；\n"
            "5. 在取得正式意见前，不建议签署不可撤销投资承诺。"
        )
    else:
        st.error(
            "**事前拦截路径建议**：\n\n"
            "1. 暂停当前选址/接入方案；\n"
            "2. 调整项目选址，避让生态保护红线、永久基本农田、一级林地等敏感区域；\n"
            "3. 如消纳红区无法解除，建议转为绿电直连、完全自发自用、用户侧储能或微电网模式；\n"
            "4. 重新论证接入电压等级与电网可开放容量；\n"
            "5. 在完成政策刚性约束核查前，不建议继续投入前期费用。"
        )

    # ------------------------------------------------------------
    # 报告下载
    # ------------------------------------------------------------

    st.subheader("📥 报告下载")

    markdown_report = build_markdown_report(
        project_type=project_type,
        address_text=project_location,
        capacity=capacity,
        selected_voltage=selected_voltage,
        recommended_voltage=recommended_voltage,
        land_use=land_use,
        consumption_zone=consumption_zone,
        self_use_ratio=self_use_ratio,
        market_participation=market_participation,
        land_res=land_res,
        grid_res=grid_res,
        voltage_res=voltage_res,
        green_res=green_res,
        risks=risks,
        finance=finance
    )

    file_name = f"湖南新能源项目合规测算报告_{project_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"

    st.download_button(
        label="下载完整测算报告（Markdown）",
        data=markdown_report,
        file_name=file_name,
        mime="text/markdown",
        type="primary"
    )

    st.divider()
    st.caption(
        "本系统为湖南省新能源政策事前拦截与投资测算演示版本。"
        "正式应用需接入湖南省自然资源厅、发改委、能源局、国网湖南电力等官方数据或经核实的GIS图层，"
        "并以政府主管部门备案、电网企业接入系统方案审查及最新政策文件为准。"
    )


# ============================================================
# 启动
# ============================================================

main()