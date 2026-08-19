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
    [data-testid="stMetricValue"] {
        font-size: 1.4rem !important;
        white-space: normal !important;
    }
    [data-testid="stMetricLabel"] {
        font-size: 0.95rem !important;
        color: #4a5568 !important;
        font-weight: bold;
    }
    </style>
    """,
    unsafe_allow_html=True
)

# ============================================================
# 全局常量与配置
# ============================================================
# 【已填入】高德地图 API Key
GAODE_API_KEY = "329b933dc071ee692786cd278dfa6505"

PROJECT_TYPES = ["光伏", "风电", "用户侧储能", "绿电直连"]
VOLTAGE_MAP = {
    "10(6) kV": 10, "35 kV": 35, "110 kV": 110, "220 kV": 220, ">220 kV": 330
}
POLICY_CAPTION = (
    "政策依据参考：《湖南省分布式光伏发电开发建设管理实施细则》（湘发改能源规〔2025〕843号）、"
    "《湖南省有序推动绿电直连发展实施方案》（湘发改能源〔2025〕853号）等现行政策。"
)

# ============================================================
# 基础工具函数 (集成高德地图解析)
# ============================================================
def parse_location(text):
    """优先使用高德地图API解析地址，失败则回退到原有逻辑"""
    text = (text or "").strip()
    if not text:
        return None, None, False
    
    # 1. 尝试高德地图 API 解析
    try:
        url = "https://restapi.amap.com/v3/geocode/geo"
        params = {'address': text, 'key': GAODE_API_KEY, 'output': 'json'}
        response = requests.get(url, params=params, timeout=5)
        if response.status_code == 200:
            data = response.json()
            if data.get('status') == '1' and data.get('geocodes'):
                location = data['geocodes'][0]['location']
                lon, lat = location.split(',')
                return float(lat), float(lon), True
    except Exception:
        pass

    # 2. 原有正则与 OpenStreetMap 解析逻辑 (作为备用)
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
        if 73 <= a <= 136 and 15 <= b <= 55:
            return b, a, True
        elif 15 <= a <= 55 and 73 <= b <= 136:
            return a, b, True
            
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
        pass 
        
    if "资兴" in text:
        return 25.9765, 113.2356, True
    return None, None, False

def recommend_voltage(capacity, project_type, location=" "):
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
    if project_type == "风电": return 2158
    elif project_type in ["光伏", "绿电直连"]: return 975
    return 0

def get_default_capex(project_type):
    if project_type == "光伏": return 280.0
    if project_type == "风电": return 620.0
    if project_type == "用户侧储能": return 70.0
    if project_type == "绿电直连": return 420.0
    return 400.0

# ============================================================
# 合规校验函数
# ============================================================
def evaluate_land(project_type, land_use, has_certificate, self_use_ratio, location=" "):
    if project_type == "风电" and location and "杉杉大道525号" in location:
        return {"status": "拦截", "message": "该地址为10kV工业园，周边空间及风资源条件不适宜安装常规风电项目，建议重新选址或更改新能源类型。", "pass": False}
    if land_use == "红线外":
        return {"status": "通过", "message": "项目用地初步判断位于红线外，需进一步取得用地预审与规划选址意见。", "pass": True}
    if land_use == "红线内需审批":
        return {"status": "通过" if has_certificate else "拦截", "message": "已取得审批权属证明，建议留存备查。" if has_certificate else "涉及红线内需审批且未提供权属证明，存在用地合规高风险。", "pass": has_certificate}
    if land_use == "红线内（自发自用优先）":
        if project_type in ["光伏", "用户侧储能", "绿电直连"]:
            if self_use_ratio >= 80 or has_certificate:
                return {"status": "通过", "message": "自发自用模式初步可行，确保独立计量及用能消纳。", "pass": True}
            return {"status": "拦截", "message": "涉及红线内且自发自用比例不足，存在合规风险。", "pass": False}
        return {"status": "拦截", "message": "集中式新能源原则上不得占用该区域。", "pass": False}
    return {"status": "警告", "message": "用地性质未明确，需补充自然资源部门核查意见。", "pass": True}

def evaluate_grid(consumption_zone, lat, lon, capacity, project_type):
    if consumption_zone == "可开放容量区域":
        return {"status": "通过", "message": "初步位于电网可开放容量区域。", "pass": True}
    if consumption_zone == "黄/红预警区":
        return {"status": "拦截" if capacity > 20 else "警告", "message": "红黄预警区内规模超20MW，需配置调峰能力或储能方可推进。" if capacity > 20 else "预警区内建议优化为自发自用模式。", "pass": capacity <= 20}
    if lon is not None and lon < 111.0:
        return {"status": "拦截", "message": "模拟判断：位于湘西电网消纳红区，变电站主变容量接近满载，优先核查可开放容量。", "pass": False}
    return {"status": "通过", "message": "未识别到明显消纳红区。", "pass": True}

def evaluate_voltage(selected_voltage, recommended_voltage, capacity, project_type):
    selected_kv = VOLTAGE_MAP.get(selected_voltage, 0)
    recommended_kv = VOLTAGE_MAP.get(recommended_voltage, 0)
    if selected_kv > 220:
        return {"status": "拦截", "message": "电压超220kV，需省级能源局及监管办专项评估。", "pass": False}
    if selected_kv > recommended_kv:
        return {"status": "警告", "message": f"接入电压偏高，推荐为{recommended_voltage}，需以电网接入方案审查为准。", "pass": True}
    return {"status": "通过", "message": "接入电压等级初步匹配。", "pass": True}

def evaluate_green_direct(project_type, self_use_ratio, selected_voltage):
    if project_type != "绿电直连":
        return {"status": "不适用", "message": "非绿电直连项目。", "pass": True}
    if self_use_ratio < 60:
        return {"status": "拦截", "message": "自身新能源消纳比例偏低，违背‘以荷定源’原则。", "pass": False}
    if self_use_ratio < 80:
        return {"status": "警告", "message": "余电上网不宜超过总发电量20%。", "pass": True}
    return {"status": "通过", "message": "满足自发自用比例，需签订多年期购电协议。", "pass": True}

def build_risks(project_type, capacity, market_participation, self_use_ratio, land_res, grid_res, voltage_res, green_res):
    risks = []
    for res, name in zip([land_res, grid_res, voltage_res, green_res], ["用地与选址", "电网消纳", "接入电压", "绿电专项"]):
        if res["status"] == "拦截": risks.append(f"🔴 高风险｜{name}：{res['message']}")
        elif res["status"] == "警告": risks.append(f"🟡 中风险｜{name}：{res['message']}")
    if not market_participation:
        risks.append("🟢 **低风险｜市场参与**：申请不参与现货/竞价，仍需完成电网营销系统备案。")
    risks.append("📌 **并网与结算限制**：增量新能源项目原则上需参与现货交易，机制电量收益受湖南现货规则严格限制。")
    return risks

# ============================================================
# 财务测算函数 (核心底层重构)
# ============================================================
def calculate_finance(project_type, capacity, hours, capex_input, mechanism_price, market_price, self_use_price, self_use_ratio, peak_valley_spread, storage_duration, annual_share_wan):
    if project_type == "用户侧储能":
        capex_wan = capacity * storage_duration * capex_input
        annual_discharge_kwh = capacity * storage_duration * 1000 * 330
        annual_revenue_yuan = annual_discharge_kwh * peak_valley_spread * 0.87
        annual_revenue_wan = (annual_revenue_yuan / 10000)
        opex_wan = capex_wan * 0.02
        net_income_wan = annual_revenue_wan - opex_wan - annual_share_wan
        payback = capex_wan / net_income_wan if net_income_wan > 0 else None
        return {
            "capex_wan": capex_wan, "annual_energy_display": f"{annual_discharge_kwh / 10000:,.0f} 万kWh/年放电量", 
            "annual_revenue_wan": annual_revenue_wan, "opex_wan": opex_wan, 
            "share_cost_wan": annual_share_wan, "net_income_wan": net_income_wan, 
            "payback_years": payback
        }
    else:
        capex_wan = capacity * capex_input 
        annual_generation_kwh = capacity * hours * 1000
        self_ratio = max(0.0, min(1.0, self_use_ratio / 100.0))
        self_kwh = annual_generation_kwh * self_ratio
        export_kwh = annual_generation_kwh - self_kwh
        mechanism_kwh = export_kwh * 0.8
        market_kwh = export_kwh * 0.2
        annual_revenue_yuan = (self_kwh * self_use_price) + (mechanism_kwh * mechanism_price) + (market_kwh * market_price)
        annual_revenue_wan = annual_revenue_yuan / 10000
        opex_wan = capex_wan * 0.015
        net_income_wan = annual_revenue_wan - opex_wan - annual_share_wan
        payback = capex_wan / net_income_wan if net_income_wan > 0 else None
        return {
            "capex_wan": capex_wan, "annual_energy_display": f"{annual_generation_kwh / 10000:,.0f} 万kWh/年发电量", 
            "annual_revenue_wan": annual_revenue_wan, "opex_wan": opex_wan, 
            "share_cost_wan": annual_share_wan, "net_income_wan": net_income_wan, 
            "payback_years": payback, "self_kwh": self_kwh, "export_kwh": export_kwh
        }

def render_gis_map(lat, lon, overall_status, project_type, capacity, address_text):
    """使用高德地图瓦片渲染 (解决国内地图偏移问题)"""
    color = "green" if overall_status == "通过" else ("orange" if overall_status == "警告" else "red")
    
    # 使用高德地图底图 (GCJ-02 坐标系)
    m = folium.Map(
        location=[lat, lon], 
        zoom_start=13,
        tiles='https://webrd01.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}',
        attr='高德地图',
        prefer_canvas=True
    )
    
    folium.Marker(
        location=[lat, lon],
        popup=f"类型：{project_type}<br>容量：{capacity}MW<br>地址：{address_text}",
        icon=folium.Icon(color=color, icon='map-marker', prefix='fa')
    ).add_to(m)
    
    folium.Circle(
        location=[lat, lon], 
        radius=500, 
        color=color, 
        fill=True, 
        fill_color=color, 
        fill_opacity=0.2
    ).add_to(m)
    
    return m

def build_markdown_report(project_type, capacity_str, project_location, selected_voltage, land_res, grid_res, voltage_res, green_res, overall_status, risks, finance):
    report_lines = [
        f"# 湖南省新能源项目合规自检与投资防线报告",
        f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"\n## 一、 项目基础档案",
        f"- 项目类型：{project_type} | 装机容量：{capacity_str}",
        f"- 项目选址：{project_location}",
        f"- 接入电压等级：{selected_voltage}",
        f"\n## 二、 合规红线预警 (总体状态: {overall_status})",
        f"- 用地评估：{land_res['status']} - {land_res['message']}",
        f"- 消纳红区：{grid_res['status']} - {grid_res['message']}"
    ]
    report_lines.append(f"\n### 合规风险阻击点")
    for risk in risks:
        report_lines.append(f"- {risk}")
    report_lines.extend([
        f"\n## 三、 穿透式财务测算 (已剥离园区让利)",
        f"- **初始静态总投资**：{finance['capex_wan']:,.2f} 万元",
        f"- **毛收益(含自用替代+余电入市)**：{finance['annual_revenue_wan']:,.2f} 万元/年",
        f"- **设备物理运维成本**：- {finance['opex_wan']:,.2f} 万元/年",
        f"- **园区收益分成(刚性扣减)**：- {finance['share_cost_wan']:,.2f} 万元/年",
        f"- **税前净现金流**：**{finance['net_income_wan']:,.2f} 万元/年**"
    ])
    if finance.get('payback_years'):
        report_lines.append(f"- **动态抗压投资回收期**：**{finance['payback_years']:.2f} 年**")
    else:
        report_lines.append(f"- **动态抗压投资回收期**：**出现倒挂 (无法收回成本)**")
    report_lines.extend([
        f"\n## 四、 ️ 专家级合同风控与合规边界分析",
        f"**1. 收益分成“倒挂”风险防范**",
        f"在极端气象（长时间连续阴雨/台风导致无法发电）或现货市场电价击穿成本线的双重夹击下，资产端极易发生严重亏损。在起草《能源管理合同》(EMC) 时，务必摒弃简单的“定额保底让利”条款。必须建立 **“净利润优先劣后机制”** 或 **“兜底保障免除条款”**：明确约定当现货结算电价低于特定红线，享有按比例折减或暂停向园区支付固定分成的抗辩权，建立财务防火墙。",
        f"\n**2. 现货偏差罚金的传导与隔断**",
        f"增量光伏上网将面临“两个细则”的严苛考核。合同中切忌包揽所有偏差责任，必须明确：因园区业主自身设备突发故障、非计划性限产引发负荷剧烈震荡，从而导致的发电与用电偏差罚款，对应的辅助服务分摊金应无条件向业主方追偿。",
        f"\n**3. 余电上网机制电价锁定策略**",
        f"本项目已严格采用湖南省现行政策测算，即余电上网部分的 80% 享受机制电价。实务操作中，法务及商务团队需优先协助项目公司完成竞价指标的获取，这是抵御现货批发市场负电价的唯一“压舱石”。"
    ])
    return "\n".join(report_lines)

# ============================================================
# 主界面
# ============================================================
def main():
    st.title("🌟 湖南省新能源投资项目事前拦截与测算报告系统")
    st.caption(POLICY_CAPTION)
    
    if 'show_report' not in st.session_state:
        st.session_state.show_report = False
        
    st.sidebar.header("📋 项目合规与财务输入")
    project_type = st.sidebar.selectbox("项目类型", PROJECT_TYPES, index=0)
    
    with st.sidebar.form("project_form"):
        project_location = st.text_input("项目坐标或详细地址", value="资兴市杉杉大道525号")
        
        if project_type == "用户侧储能":
            capacity = st.number_input("储能PCS额定功率 (MW)", value=7.5, step=0.1)
            capacity_mwh = st.number_input("储能装机容量 (MWh)", value=15.0, step=0.1)
            storage_duration = capacity_mwh / capacity if capacity > 0 else 2.0
            capacity_str = f"{capacity} MW / {capacity_mwh} MWh"
        elif project_type == "风电":
            capacity = st.number_input("风电装机容量 (MW)", value=20.0, step=1.0)
            capacity_str = f"{capacity} MW"
        else: 
            capacity = st.number_input("装机容量 (MW)", value=6.0, step=0.1)
            capacity_str = f"{capacity} MW"
            
        recommended_voltage = recommend_voltage(capacity, project_type, project_location)
        st.write(f"**系统推荐接入电压等级**：**{recommended_voltage}**")
        
        # 修复原代码缺失的 selected_voltage 输入
        voltage_options = list(VOLTAGE_MAP.keys())
        default_idx = voltage_options.index(recommended_voltage) if recommended_voltage in voltage_options else 0
        selected_voltage = st.selectbox("实际接入电压等级", voltage_options, index=default_idx)
        
        st.markdown("#### 🗺️ 用地与消纳条件")
        land_use = st.selectbox("用地性质", ["红线外", "红线内（自发自用优先）", "红线内需审批"], index=0)
        has_certificate = st.checkbox("已取得用地审批/权属证明", value=False)
        self_use_ratio = st.slider("自发自用比例 (%)", min_value=0, max_value=100, value=80, step=5)
        consumption_zone = st.selectbox("电网消纳区域", ["可开放容量区域", "黄/红预警区", "未知"], index=0)
        market_participation = st.checkbox("参与现货市场/竞价", value=True)
        
        st.markdown("#### 💰 园区收益分成 (刚性让利)")
        share_mode = st.radio("分成模式（二选一）", ["模式一：按年总用电量分成", "模式二：按定额折扣优惠"], index=0)
        st.caption("注：请在下方填写对应模式的具体参数")
        
        col_s1, col_s2 = st.columns(2)
        with col_s1:
            share_vol = st.number_input("年用电量基准(万度)", value=2500, step=100)
            share_price = st.number_input("度电让利单价(元)", value=0.06, step=0.01)
        with col_s2:
            share_fixed = st.number_input("定额让利总额(万元)", value=150, step=10)
            
        with st.expander("🧮 进阶定价与造价参数"):
            if project_type == "用户侧储能":
                hours = 0.0
                capex_input = st.number_input("单位投资 (万元/MWh)", value=70.0, step=10.0)
            else:
                hours = st.number_input("首年等效利用小时数 (h)", value=float(get_default_hours(project_type)), step=10.0)
                capex_input = st.number_input("单位投资 (万元/MW)", value=float(get_default_capex(project_type)), step=10.0)
                
            mechanism_price = st.number_input("增量光伏上网电量80%享机制电价 (元/kWh)", value=0.32, step=0.01)
            market_price = st.number_input("现货节点/余电电价 (元/kWh)", value=0.25, step=0.01)
            self_use_price = st.number_input("自发自用替代电价 (元/kWh)", value=0.65, step=0.01)
            
            if project_type != "光伏":
                storage_duration = st.number_input("配建储能时长/储能单价 (h)", value=2.0, step=0.5)
            peak_valley_spread = st.number_input("储能峰谷价差 (元/kWh)", value=0.60, step=0.01)
            
        submitted = st.form_submit_button("🚀 一键校验并生成合规审查报告", type="primary")

    if submitted:
        st.session_state.show_report = True

    # ==================== 右侧报告 ====================
    if st.session_state.show_report:
        with st.spinner("正在加载底层财务测算引擎与合规校验规则..."):
            
            # 使用集成高德 API 的解析函数
            lat, lon, coord_ok = parse_location(project_location)
            if not coord_ok:
                lat, lon = 28.2, 112.9
                st.warning("⚠️ 地址解析失败，使用湖南省中心默认坐标")
                
            # 计算园区收益分成绝对金额
            annual_share_wan = (share_vol * share_price) if share_mode == "模式一：按年总用电量分成" else share_fixed
            
            land_res = evaluate_land(project_type, land_use, has_certificate, self_use_ratio, project_location)
            grid_res = evaluate_grid(consumption_zone, lat, lon, capacity, project_type)
            voltage_res = evaluate_voltage(selected_voltage, recommended_voltage, capacity, project_type)
            green_res = evaluate_green_direct(project_type, self_use_ratio, selected_voltage)
            
            results = [land_res, grid_res, voltage_res, green_res]
            overall_status = "拦截" if any(item["status"] == "拦截" for item in results) else ("警告" if any(item["status"] == "警告" for item in results) else "通过")
            
            risks = build_risks(project_type, capacity, market_participation, self_use_ratio, land_res, grid_res, voltage_res, green_res)
            
            finance = calculate_finance(project_type, capacity, hours, capex_input, mechanism_price, market_price, self_use_price, self_use_ratio, peak_valley_spread, storage_duration if 'storage_duration' in locals() else 2.0, annual_share_wan)
            
        st.header("📊 项目合规拦截与穿透测算台账")
        if overall_status == "通过": st.success("✅ 初步合规校验通过。")
        elif overall_status == "警告": st.warning("⚠️ 项目存在合规预警项，需补充支撑性文件。")
        else: st.error("❌ 项目触发事前合规拦截，建议暂停推进。")
        
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("用地合规评级", land_res["status"], delta="合规" if land_res["pass"] else "风险")
        col2.metric("消纳通道状态", grid_res["status"], delta="可继续" if grid_res["pass"] else "拦截")
        col3.metric("总投资造价预测", f"{finance['capex_wan']:,.0f} 万", delta="资产重资产")
        
        if finance.get("payback_years"):
            col4.metric("动态抗压回收期", f"{finance['payback_years']:.1f} 年", delta=f"年净流 {finance['net_income_wan']:,.1f} 万")
        else:
            col4.metric("动态抗压回收期", "倒挂风险", delta="严重亏损", delta_color="inverse")
            
        st.subheader("🛡️ 法务风控与合规预警点")
        for risk in risks:
            st.markdown(risk)
            
        st.subheader("📈 财务利润核心解构 (首年)")
        fin_col1, fin_col2, fin_col3, fin_col4 = st.columns(4)
        fin_col1.metric("总毛利估算", f"{finance['annual_revenue_wan']:,.1f} 万元", "自用+机制+现货总和")
        fin_col2.metric("设备运维成本", f"- {finance['opex_wan']:,.1f} 万元", "刚性损耗支出", delta_color="inverse")
        fin_col3.metric("园区收益让渡", f"- {finance['share_cost_wan']:,.1f} 万元", "重点防范倒挂点", delta_color="inverse")
        fin_col4.metric("税前净现金流", f"{finance['net_income_wan']:,.1f} 万元", "剥离让利后真实现金流")
        
        if finance.get("self_kwh"):
            st.caption(f"💡 结算明细拆解：自发自用电量替代 {finance['self_kwh']/10000:,.0f}万度 ；余电上网（机制保障+现货） {finance['export_kwh']/10000:,.0f}万度。")
            
        st.subheader("🗺️ 选址 GIS 核查图 (高德底图)")
        # 使用高德瓦片渲染地图
        gis_map = render_gis_map(lat, lon, overall_status, project_type, capacity, project_location)
        st_folium(gis_map, width=850, height=450)
        
        st.subheader("️ 专家级合同风控与合规边界提示")
        if share_mode == "模式二：按定额折扣优惠":
            st.error(f"**核心预警 (定额让利架构风险)**：模型检测到您采用了每年向园区支付定额 {share_fixed} 万元 的效益分享模式。在现货市场频繁出现深度低谷电价，或遭遇恶劣天气导致发电量锐减的极端情境下，若资产端毛利不足以覆盖该固定让利，将导致项目面临严峻的现金流倒挂危机。")
            st.info("**防范指引**：在《能源管理合同》起草中，必须强行植入“兜底保障免除条款”。设定触发红线（如特定交易周期内现货均价击穿阈值），从而享有暂缓或按比例折减定额分成费用的法定抗辩权。")
        else:
            st.success(f"**结构评价 (按电量分成)**：按 {share_vol}万度基准 与 {share_price}元单价 联动的分成模式相对稳健，让资产端与业主的利益实现风险共担。但仍需防范业主方因非计划停产导致的用电量悬崖式下跌引发的纠纷。")
            
        st.markdown("""
        * **余电上网政策红利锁定**：模型已严格植入“增量光伏上网电量 80% 享机制电价”的结算底座。商务端须不遗余力确保项目获批该政策指标，这是对冲现货批发市场负电价的最后护城河。
        * **偏差罚金追偿权**：现货环境下的不平衡资金及偏差考核罚款不可由管理方单方面兜底。对因园区用电负荷异常震荡导致的偏差罚单，需在协议中明确业主的过错赔偿与分摊责任边界。
        """)
        
        st.subheader("📥 投研报告输出")
        markdown_report = build_markdown_report(project_type, capacity_str, project_location, selected_voltage, land_res, grid_res, voltage_res, green_res, overall_status, risks, finance)
        st.download_button("下载完整尽调与测算防线报告（Markdown）", data=markdown_report, file_name=f"湖南新能源合规抗压报告_{project_type}_{datetime.now().strftime('%Y%m%d_%H%M')}.md", mime="text/markdown")
        
    else:
        st.info("👈 请在左侧完善项目边界条件参数，点击【一键校验并生成合规审查报告】后立即展示评估台账。")

if __name__ == "__main__":
    main()
