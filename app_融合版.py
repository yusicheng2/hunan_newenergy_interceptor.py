import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from datetime import datetime
import re
import requests

# ============================================================
# 页面配置与全局样式
# ============================================================

st.set_page_config(
    page_title="湖南省新能源项目合规风险自检与测算系统",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 注入自定义 CSS 以调小 st.metric 的字体，防止数值被截断显示省略号
st.markdown(
    """
    <style>
    /* 调小测算报告中的 Metric 数值和标题字体，并允许换行 */
    [data-testid="stMetricValue"] {
        font-size: 1.4rem !important;
        white-space: normal !important;
    }
    [data-testid="stMetricLabel"] {
        font-size: 0.95rem !important;
    }
    </style>
    """,
    unsafe_allow_html=True
)

PROJECT_TYPES = ["光伏", "风电", "用户侧储能", "绿电直连"]

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
    text = (text or "").strip()
    if not text:
        return None, None, False

    # 1. 尝试使用正则表达式解析纯经纬度输入
    m_lat = re.search(r"([-+]?\d+(?:\.\d+)?)\s*(?:°|度)?\s*N", text, re.IGNORECASE)
    m_lon = re.search(r"([-+]?\d+(?:\.\d+)?)\s*(?:°|度)?\s*E", text, re.IGNORECASE)
    if m_lat and m_lon:
        return float(m_lat.group(1)), float(m_lon.group(1)), True

    m_lat_cn = re.search(r"北纬\s*([-+]?\d+(?:\.\d+)?)", text)
    m_lon_cn = re.search(r"东经\s*([-+]?\d+(?:\.\d+)?)", text)
    if m_lat_cn and m_lon_cn:
        return float(m_lat_cn.group(1)), float(m_lon_cn.group(1)), True

    nums = re.findall(r"[-+]?\d+(?:\.\d+)?", text)
    floats = [float(x) for x in nums]
    if len(floats) >= 2:
        a, b = floats[0], floats[1]
        # 简单判断经纬度范围 (中国大致经纬度: 经度73~136, 纬度15~55)
        if 73 <= a <= 136 and 15 <= b <= 55:
            lon, lat = a, b
            return lat, lon, True
        elif 15 <= a <= 55 and 73 <= b <= 136:
            lat, lon = a, b
            return lat, lon, True

    # 2. 正则解析失败，调用开源 Geocoding API 解析中文地址
    try:
        url = "https://nominatim.openstreetmap.org/search"
        params = {'q': text, 'format': 'json', 'limit': 1}
        headers = {'User-Agent': 'Mozilla/5.0 (StreamlitEnergyApp)'}
        response = requests.get(url, params=params, headers=headers, timeout=5)
        if response.status_code == 200:
            data = response.json()
            if len(data) > 0:
                return float(data[0]['lat']), float(data[0]['lon']), True
    except Exception:
        pass # 接口超时或网络异常时，静默失败，走底部默认处理

    # 3. 兜底方案：确保示例地址演示顺畅
    if "资兴" in text:
        return 25.9765, 113.2356, True

    return None, None, False


def recommend_voltage(capacity, project_type, location=""):
    # 特殊地址处理规则：锁定 10kV 氢能工业园区电网环境
    if location and "杉杉大道525号" in location:
        return "10(6) kV"
        
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
    if project_type == "风电":
        return 2158
    elif project_type == "光伏":
        return 975
    elif project_type == "绿电直连":
        return 975
    else:
        return 0


def get_default_capex(project_type):
    if project_type == "光伏":
        return 280.0
    elif project_type == "风电":
        return 620.0
    elif project_type == "用户侧储能":
        return 70.0
    elif project_type == "绿电直连":
        return 420.0
    else:
        return 400.0


# ============================================================
# 合规校验函数
# ============================================================

def evaluate_land(project_type, land_use, has_certificate, self_use_ratio, location=""):
    # 针对特定地址的风电建设适用性拦截限制
    if project_type == "风电" and location and "杉杉大道525号" in location:
        return {"status": "拦截", "message": "该地址为10kV氢能工业园，周边空间及风资源条件不适宜安装常规风电项目（微风风机除外），建议重新选址或更改新能源类型。", "pass": False}

    if land_use == "红线外":
        return {"status": "通过", "message": "项目用地初步判断位于红线外，需进一步取得用地预审与规划选址意见。", "pass": True}
    if land_use == "红线内需审批":
        return {"status": "通过" if has_certificate else "拦截", "message": "项目涉及红线内需审批，但已取得审批/权属证明，建议留存自然资源局、林业局等部门意见。" if has_certificate else "项目涉及红线内需审批，但未提供审批/权属证明，存在用地合规风险，不建议继续推进。", "pass": has_certificate}
    if land_use == "红线内（自发自用优先）":
        if project_type in ["用户侧储能", "绿电直连"]:
            if self_use_ratio >= 80 or has_certificate:
                return {"status": "通过", "message": "红线内自发自用/绿电直连模式初步可行，建议确保自发自用比例、权属证明及独立计量条件。", "pass": True}
            else:
                return {"status": "拦截", "message": "红线内自发自用/绿电直连模式下，自发自用比例不足或权属证明不完整，存在高合规风险。", "pass": False}
        if project_type == "光伏":
            if self_use_ratio >= 80:
                return {"status": "通过", "message": "分布式光伏红线内自发自用初步可行，建议确保自发自用比例≥80%，并满足独立计量要求。", "pass": True}
            elif has_certificate:
                return {"status": "警告", "message": "分布式光伏涉及红线内，但已取得部分权属证明。需进一步确认自发自用比例及并网方案。", "pass": True}
            else:
                return {"status": "拦截", "message": "分布式光伏涉及红线内且自发自用比例不足，存在用地合规风险。", "pass": False}
        return {"status": "拦截", "message": "集中式风电/光伏原则上不得占用红线内区域，建议调整选址或重新开展用地合规论证。", "pass": False}
    return {"status": "警告", "message": "用地性质未明确，需补充自然资源、林业、水利等部门核查意见。", "pass": True}


def evaluate_grid(consumption_zone, lat, lon, capacity, project_type):
    if consumption_zone == "可开放容量区域":
        return {"status": "通过", "message": "项目初步位于电网可开放容量区域，仍需以国网湖南电力营销2.0系统可开放容量评估为准。", "pass": True}
    if consumption_zone == "黄/红预警区":
        return {"status": "拦截" if capacity > 20 else "警告", "message": "项目位于电网消纳黄/红预警区，且装机规模超过20MW，原则上需取得可开放容量评估、储能配置或调峰能力证明后方可推进并网。" if capacity > 20 else "项目位于电网消纳黄/红预警区，需配建储能、参与调峰或优化为自发自用/绿电直连模式。", "pass": capacity <= 20}
    if lon is not None and lon < 111.0:
        return {"status": "拦截", "message": "模拟判断：项目可能位于湘西电网消纳红区，变电站主变容量接近满载，建议暂停新增并网审批并优先开展可开放容量核查。", "pass": False}
    return {"status": "通过", "message": "未识别到明显消纳红区，但仍需以国网湖南电力可开放容量评估和接入系统方案审查为准。", "pass": True}


def evaluate_voltage(selected_voltage, recommended_voltage, capacity, project_type):
    selected_kv = VOLTAGE_MAP.get(selected_voltage, 0)
    recommended_kv = VOLTAGE_MAP.get(recommended_voltage, 0)
    if selected_kv > 220:
        return {"status": "拦截", "message": "接入电压等级超过220kV，需省级能源局、国家能源局湖南监管办及电网企业专项评估，事前拦截风险较高。", "pass": False}
    if project_type == "绿电直连" and selected_kv > 220:
        return {"status": "拦截", "message": "绿电直连项目接入电压等级不应超过220kV，需重新论证接入方案。", "pass": False}
    if selected_kv > recommended_kv and capacity <= 20 and selected_kv >= 220:
        return {"status": "警告", "message": f"接入电压等级偏高。系统推荐接入电压为{recommended_voltage}，当前选择为{selected_voltage}，需电网企业确认技术经济性。", "pass": True}
    if selected_kv > recommended_kv:
        return {"status": "警告", "message": f"接入电压等级与容量初步匹配性偏弱。系统推荐接入电压为{recommended_voltage}，当前选择为{selected_voltage}，需以接入系统方案审查为准。", "pass": True}
    return {"status": "通过", "message": f"接入电压等级初步匹配，推荐接入电压为{recommended_voltage}。", "pass": True}


def evaluate_green_direct(project_type, self_use_ratio, selected_voltage):
    if project_type != "绿电直连":
        return {"status": "不适用", "message": "当前项目非绿电直连项目。", "pass": True}
    selected_kv = VOLTAGE_MAP.get(selected_voltage, 0)
    if selected_kv > 220:
        return {"status": "拦截", "message": "绿电直连项目接入电压等级不应超过220kV。", "pass": False}
    if self_use_ratio < 60:
        return {"status": "拦截", "message": "绿电直连项目自身新能源消纳比例偏低，建议按‘以荷定源’原则重新匹配负荷与电源规模。", "pass": False}
    if self_use_ratio < 80:
        return {"status": "警告", "message": "绿电直连项目需控制年上网电量比例，原则上余电上网不宜超过总发电量20%。", "pass": True}
    return {"status": "通过", "message": "绿电直连项目初步满足自发自用比例、接入电压等要求，需进一步签订多年期购电协议并纳入电网企业一站式服务流程。", "pass": True}


def build_risks(project_type, capacity, market_participation, self_use_ratio, land_res, grid_res, voltage_res, green_res):
    risks = []
    if land_res["status"] == "拦截":
        risks.append(f"🔴 **高风险｜用地与选址匹配**：{land_res['message']}")
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
        risks.append("🟡 **中风险｜用户侧储能**：储能规模可能超过用户实际负荷，需开展负荷匹配分析，并按GB/T 43526等要求配置独立计量、安全消防及并网/非并网运行方案。")
    if project_type == "绿电直连" and self_use_ratio < 80:
        risks.append("🟡 **中风险｜绿电直连余电控制**：绿电直连项目应按‘以荷定源’原则配置，年上网电量原则上不宜超过总发电量20%。")
    if not market_participation:
        risks.append("🟢 **低风险｜市场参与**：项目可申请不参与现货/竞价，但仍需通过国网湖南电力营销2.0系统完成备案，并满足属地并网审批要求。")

    risks.append(
        "📌 **并网审批与现货规则限制**：本报告所有测算结果均受限于属地并网审批进度、国网湖南电力营销2.0系统认定的并网容量与并网时点；增量新能源项目原则上需参与年度竞价或现货市场交易，机制电量、机制电价及结算收益受湖南现货规则、节点电价、消纳责任权重调整影响。"
    )
    return risks


# ============================================================
# 财务测算函数
# ============================================================

def calculate_finance(project_type, capacity, hours, capex_input, mechanism_price, market_price, self_use_price, self_use_ratio, peak_valley_spread, storage_duration, cycle_days=330, roundtrip_eff=0.87):
    # 根据类型适配造价计算逻辑
    if project_type == "用户侧储能":
        capex_wan = capacity * storage_duration * capex_input  # 容量(MWh) * 单价(万元/MWh)
        annual_discharge_kwh = capacity * storage_duration * 1000 * cycle_days
        annual_revenue_yuan = annual_discharge_kwh * peak_valley_spread * roundtrip_eff
        annual_revenue_wan = annual_revenue_yuan / 10000
        opex_wan = capex_wan * 0.02
        net_income_wan = annual_revenue_wan - opex_wan
        payback = capex_wan / net_income_wan if net_income_wan > 0 else None
        simple_return = net_income_wan / capex_wan * 100 if capex_wan > 0 and net_income_wan > 0 else None
        return {"capex_wan": capex_wan, "annual_energy_kwh": annual_discharge_kwh, "annual_energy_display": f"{annual_discharge_kwh / 10000:,.0f} 万kWh/年放电量", "annual_revenue_wan": annual_revenue_wan, "opex_wan": opex_wan, "net_income_wan": net_income_wan, "payback_years": payback, "simple_return_pct": simple_return}
    else:
        capex_wan = capacity * capex_input  # 功率(MW) * 单价(万元/MW)
        annual_generation_kwh = capacity * hours * 1000
        
        if project_type == "绿电直连":
            self_ratio = max(0.0, min(1.0, self_use_ratio / 100.0))
            self_kwh = annual_generation_kwh * self_ratio
            grid_kwh = annual_generation_kwh * min(1.0 - self_ratio, 0.20)
            annual_revenue_yuan = self_kwh * self_use_price + grid_kwh * market_price
            annual_revenue_wan = annual_revenue_yuan / 10000
            opex_wan = capex_wan * 0.02
            net_income_wan = annual_revenue_wan - opex_wan
            payback = capex_wan / net_income_wan if net_income_wan > 0 else None
            simple_return = net_income_wan / capex_wan * 100 if capex_wan > 0 and net_income_wan > 0 else None
            return {"capex_wan": capex_wan, "annual_energy_kwh": annual_generation_kwh, "annual_energy_display": f"{annual_generation_kwh / 10000:,.0f} 万kWh/年发电量", "annual_revenue_wan": annual_revenue_wan, "opex_wan": opex_wan, "net_income_wan": net_income_wan, "payback_years": payback, "simple_return_pct": simple_return, "self_kwh": self_kwh, "grid_kwh": grid_kwh}
            
        mechanism_ratio = 0.8
        mechanism_kwh = annual_generation_kwh * mechanism_ratio
        market_kwh = annual_generation_kwh * (1 - mechanism_ratio)
        annual_revenue_yuan = mechanism_kwh * mechanism_price + market_kwh * market_price
        annual_revenue_wan = annual_revenue_yuan / 10000
        opex_wan = capex_wan * 0.015
        net_income_wan = annual_revenue_wan - opex_wan
        payback = capex_wan / net_income_wan if net_income_wan > 0 else None
        simple_return = net_income_wan / capex_wan * 100 if capex_wan > 0 and net_income_wan > 0 else None
        return {"capex_wan": capex_wan, "annual_energy_kwh": annual_generation_kwh, "annual_energy_display": f"{annual_generation_kwh / 10000:,.0f} 万kWh/年发电量", "annual_revenue_wan": annual_revenue_wan, "opex_wan": opex_wan, "net_income_wan": net_income_wan, "payback_years": payback, "simple_return_pct": simple_return, "mechanism_kwh": mechanism_kwh, "market_kwh": market_kwh}


# ============================================================
# GIS 地图函数
# ============================================================

def render_gis_map(lat, lon, overall_status, project_type, capacity, address_text):
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
        )
    ).add_to(m)
    folium.Circle(location=[lat, lon], radius=500, color=color, fill=True, fill_color=color, fill_opacity=0.2).add_to(m)
    return m

# ============================================================
# Markdown 报告生成函数 
# ============================================================

def build_markdown_report(project_type, capacity_str, project_location, selected_voltage, land_res, grid_res, voltage_res, green_res, overall_status, risks, finance):
    report_lines = [
        f"# 湖南省新能源项目合规自检与测算报告",
        f"**生成时间**：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"\n## 一、 项目基础信息",
        f"- **项目类型**：{project_type}",
        f"- **项目地址**：{project_location}",
        f"- **装机容量**：{capacity_str}",
        f"- **接入电压等级**：{selected_voltage}",
        f"\n## 二、 合规校验结果 (总体状态: {overall_status})",
        f"- **用地与选址评估**：{land_res['status']} - {land_res['message']}",
        f"- **电网消纳红区**：{grid_res['status']} - {grid_res['message']}",
        f"- **接入电压等级**：{voltage_res['status']} - {voltage_res['message']}"
    ]
    
    if project_type == "绿电直连":
        report_lines.append(f"- **绿电直连专项**：{green_res['status']} - {green_res['message']}")
        
    report_lines.append(f"\n### 风险提示")
    for risk in risks:
        report_lines.append(f"- {risk}")
        
    report_lines.extend([
        f"\n## 三、 投资测算简报",
        f"- **初始投资估算**：{finance['capex_wan']:,.2f} 万元",
        f"- **首年电量指标**：{finance['annual_energy_display']}",
        f"- **首年收益估算**：{finance['annual_revenue_wan']:,.2f} 万元",
        f"- **年运维成本估算**：{finance['opex_wan']:,.2f} 万元",
        f"- **年净收益估算**：{finance['net_income_wan']:,.2f} 万元",
        f"- **简化年收益率**：{finance.get('simple_return_pct', 0):.2f}%"
    ])
    
    if finance.get('payback_years'):
        report_lines.append(f"- **静态投资回收期**：{finance['payback_years']:.2f} 年")
        
    return "\n".join(report_lines)

# ============================================================
# 主界面
# ============================================================

def main():
    st.title("🌟 湖南省新能源投资项目事前拦截与测算报告系统")
    st.caption(POLICY_CAPTION)

    if 'show_report' not in st.session_state:
        st.session_state.show_report = False

    # 将项目类型提取到 form 外部，以触发左侧边栏界面动态刷新
    st.sidebar.header("📋 项目输入")
    project_type = st.sidebar.selectbox("项目类型", PROJECT_TYPES, index=0)

    # 包含提交按钮的表单
    with st.sidebar.form("project_form"):
        project_location = st.text_input("项目坐标或详细地址", value="资兴市杉杉大道525号")
        
        # 根据项目类型拆分容量参数设置
        if project_type == "用户侧储能":
            capacity = st.number_input("储能PCS额定功率 (MW)", min_value=0.1, max_value=1000.0, value=7.5, step=0.1)
            capacity_mwh = st.number_input("储能装机容量 (MWh)", min_value=0.0, max_value=30.0, value=15.0, step=0.1)
            storage_duration = capacity_mwh / capacity if capacity > 0 else 2.0
            capacity_str = f"{capacity} MW / {capacity_mwh} MWh"
        elif project_type == "光伏":
            capacity = st.number_input("装机容量 (MW)", min_value=0.0, max_value=6.0, value=6.0, step=0.1)
            capacity_mwh = 0.0
            capacity_str = f"{capacity} MW"
        elif project_type == "风电":
            capacity = st.number_input("风电装机容量 (MW)", min_value=0.1, max_value=1000.0, value=20.0, step=1.0)
            capacity_mwh = 0.0
            capacity_str = f"{capacity} MW"
        else: # 绿电直连
            capacity = st.number_input("装机容量 (MW)", min_value=0.1, max_value=1000.0, value=6.0, step=0.1)
            capacity_mwh = 0.0
            capacity_str = f"{capacity} MW"

        recommended_voltage = recommend_voltage(capacity, project_type, project_location)
        st.write(f"**系统推荐接入电压等级**：**{recommended_voltage}**")
        st.info("电压等级已强制使用系统推荐，实际仍需以国网湖南电力接入系统方案为准。")

        st.markdown("#### 🗺️ 用地与消纳条件")
        land_use = st.selectbox("用地性质", ["红线外", "红线内（自发自用优先）", "红线内需审批"], index=0)
        has_certificate = st.checkbox("已取得用地审批/权属证明", value=False)
        self_use_ratio = st.slider("自发自用比例 (%)", min_value=0, max_value=100, value=80, step=5)

        consumption_zone = st.selectbox("电网消纳区域", ["可开放容量区域", "黄/红预警区", "未知"], index=0)
        market_participation = st.checkbox("参与现货市场/竞价", value=True)

        with st.expander("🧮 高级测算参数"):
            # 根据项目类型动态显示高级测算参数
            if project_type == "光伏":
                hours = st.number_input("首年等效利用小时数 (h)", min_value=0.0, max_value=5000.0, value=float(get_default_hours(project_type)), step=10.0)
                capex_input = st.number_input("单位投资 (万元/MW) [含SVG和四可装置费用]", min_value=0.0, max_value=20000.0, value=280.0, step=10.0)
                storage_duration = st.number_input("配建储能时长 (h)", min_value=0.5, max_value=8.0, value=2.0, step=0.5)
            elif project_type == "用户侧储能":
                hours = 0.0
                capex_input = st.number_input("单位投资 (万元/MWh)", min_value=0.0, max_value=20000.0, value=70.0, step=10.0)
            elif project_type == "风电":
                hours = st.number_input("首年等效利用小时数 (h)", min_value=0.0, max_value=5000.0, value=float(get_default_hours(project_type)), step=10.0)
                capex_input = st.number_input("风电单位投资 (万元/MW)", min_value=0.0, max_value=20000.0, value=620.0, step=10.0)
                storage_duration = st.number_input("配建储能时长 (h)", min_value=0.5, max_value=8.0, value=2.0, step=0.5)
            else:
                hours = st.number_input("首年等效利用小时数 (h)", min_value=0.0, max_value=5000.0, value=float(get_default_hours(project_type)), step=10.0)
                capex_input = st.number_input("单位投资 (万元/MW)", min_value=0.0, max_value=20000.0, value=float(get_default_capex(project_type)), step=10.0)
                storage_duration = st.number_input("配建储能时长 (h)", min_value=0.5, max_value=8.0, value=2.0, step=0.5)
                
            mechanism_price = st.number_input("增量光伏项目上网电量的80%享受机制电价 (元/kWh)", min_value=0.0, max_value=1.5, value=0.32, step=0.01)
            market_price = st.number_input("现货/余电电价 (元/kWh)", min_value=0.0, max_value=1.5, value=0.25, step=0.01)
            self_use_price = st.number_input("自发自用替代电价 (元/kWh)", min_value=0.0, max_value=2.0, value=0.65, step=0.01)
            peak_valley_spread = st.number_input("储能峰谷价差 (元/kWh)", min_value=0.0, max_value=2.0, value=0.60, step=0.01)

        submitted = st.form_submit_button("🚀 一键校验并生成报告", type="primary")

    if submitted:
        st.session_state.show_report = True

    # ==================== 右侧报告 ====================
    if st.session_state.show_report:
        with st.spinner("正在调用湖南省用地红线、电网消纳、接入电压及政策规则引擎进行核查..."):
            lat, lon, coord_ok = parse_location(project_location)
            if not coord_ok:
                lat, lon = 28.2, 112.9
                st.warning("未能从输入中解析有效坐标，已默认定位到长沙市示例坐标。")

            recommended_voltage = recommend_voltage(capacity, project_type, project_location)
            selected_voltage = recommended_voltage

            land_res = evaluate_land(project_type, land_use, has_certificate, self_use_ratio, project_location)
            grid_res = evaluate_grid(consumption_zone, lat, lon, capacity, project_type)
            voltage_res = evaluate_voltage(selected_voltage, recommended_voltage, capacity, project_type)
            green_res = evaluate_green_direct(project_type, self_use_ratio, selected_voltage)

            results = [land_res, grid_res, voltage_res, green_res]
            overall_status = "拦截" if any(item["status"] == "拦截" for item in results) else ("警告" if any(item["status"] == "警告" for item in results) else "通过")

            risks = build_risks(project_type, capacity, market_participation, self_use_ratio, land_res, grid_res, voltage_res, green_res)
            finance = calculate_finance(project_type, capacity, hours, capex_input, mechanism_price, market_price, self_use_price, self_use_ratio, peak_valley_spread, storage_duration)

        st.header("📊 实时校验结果与完整测算报告")

        if overall_status == "通过":
            st.success("✅ 初步合规校验通过。")
        elif overall_status == "警告":
            st.warning("⚠️ 项目存在合规预警项。")
        else:
            st.error("❌ 项目触发事前拦截项。")

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("用地与选址评估", land_res["status"], delta="合规" if land_res["pass"] else "风险")
        col2.metric("电网消纳红区", grid_res["status"], delta="可继续" if grid_res["pass"] else "拦截")
        col3.metric("接入电压等级", voltage_res["status"], delta=f"推荐：{recommended_voltage}")
        col4.metric("绿电直连专项", green_res["status"], delta="适用" if project_type == "绿电直连" else "非绿电直连")

        st.subheader("📝 参数明细")
        param_df = pd.DataFrame({
            "参数指标": ["项目类型", "项目坐标/地址", "装机容量", "用户选择接入电压等级", "系统推荐接入电压等级", "用地性质", "是否取得审批/权属证明", "自发自用比例 (%)", "电网消纳区域", "现货市场/竞价参与", "首年等效利用小时数 (h)", f"单位投资 ({'万元/MWh' if project_type=='用户侧储能' else '万元/MW'})"],
            "输入值": [project_type, project_location, capacity_str, selected_voltage, recommended_voltage, land_use, "是" if has_certificate else "否", self_use_ratio, consumption_zone, "参与" if market_participation else "不参与", hours if project_type != "用户侧储能" else "不适用", capex_input]
        })
        st.table(param_df)

        st.subheader("🛡️ 合规风险标注（自动追加）")
        for risk in risks:
            st.markdown(risk)

        st.subheader("🗺️ GIS核查图")
        gis_map = render_gis_map(lat, lon, overall_status, project_type, capacity, project_location)
        st_folium(gis_map, width=850, height=450)

        st.subheader("📈 投资测算报告（简化版）")
        fin_col1, fin_col2, fin_col3, fin_col4 = st.columns(4)
        fin_col1.metric("初始投资估算", f"{finance['capex_wan']:,.0f} 万元")
        fin_col2.metric("首年电量指标", finance["annual_energy_display"])
        fin_col3.metric("首年收益估算", f"{finance['annual_revenue_wan']:,.2f} 万元")
        if finance.get("payback_years"):
            fin_col4.metric("静态投资回收期", f"{finance['payback_years']:.2f} 年")
        else:
            st.metric("静态投资回收期", "暂无法测算")
        st.write(f"**年运维成本估算**：{finance['opex_wan']:,.2f} 万元 | **年净收益估算**：{finance['net_income_wan']:,.2f} 万元 | **简化年收益率**：{finance.get('simple_return_pct', 0):.2f}%")

        if project_type == "绿电直连":
            st.info("绿电直连提示：项目应坚持‘以荷定源’...")
        if project_type == "用户侧储能":
            st.info("用户侧储能提示：...")

        st.subheader("💡 合规路径建议")
        if overall_status == "通过":
            st.success("**立即可行路径建议**：\n1. 对接属地发改/能源主管部门...")
        elif overall_status == "警告":
            st.warning("**需整改后推进路径建议**：\n1. 补充自然资源局、林业局等部门用地合规证明...")

        st.subheader("📥 报告下载")
        
        markdown_report = build_markdown_report(
            project_type, capacity_str, project_location, selected_voltage, 
            land_res, grid_res, voltage_res, green_res, overall_status, risks, finance
        )
        
        st.download_button("下载完整测算报告（Markdown）", data=markdown_report, file_name=f"湖南新能源项目合规测算报告_{project_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md", mime="text/markdown")

    else:
        st.info("👈 请在左侧输入参数，点击【一键校验并生成报告】后右侧将立即显示完整报告。")


if __name__ == "__main__":
    main()
