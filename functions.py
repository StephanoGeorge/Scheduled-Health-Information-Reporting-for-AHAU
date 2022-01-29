region_code = ['340000', '340100', '340104']
region_name = ['安徽省', '合肥市', '蜀山区']


def page_js_code():
    return f'''
() => {{
    function getElementByXpath(path) {{
        return document.evaluate(path, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
    }}
    $('#dqszdmc').val('{''.join(region_name)}');
    $('#dqszddm').val('{region_code[-1]}');
    getElementByXpath("//dl/dd[@lay-value='健康']").click();
}}
'''


if __name__ == '__main__':
    print(page_js_code())
