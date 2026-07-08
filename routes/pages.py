"""
智能家居系统 - 页面路由
渲染 HTML 模板页面
"""
from flask import Blueprint, render_template

pages_bp = Blueprint('pages', __name__)


@pages_bp.route('/')
def dashboard():
    """主仪表盘"""
    return render_template('dashboard.html', active_page='dashboard')


@pages_bp.route('/access')
def access_control():
    """门禁管理页面"""
    return render_template('access_control.html', active_page='access')


@pages_bp.route('/detection')
def object_detection():
    """物体检测页面"""
    return render_template('object_detection.html', active_page='detection')


@pages_bp.route('/devices')
def device_control():
    """设备控制页面"""
    return render_template('device_control.html', active_page='devices')


@pages_bp.route('/analysis')
def data_analysis():
    """数据分析页面"""
    return render_template('data_analysis.html', active_page='analysis')


@pages_bp.route('/persons')
def person_management():
    """授权人员管理页面"""
    return render_template('persons.html', active_page='persons')
