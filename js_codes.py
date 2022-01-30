REGION_CODE = ['340000', '340100', '340104']
REGION_NAME = ['安徽省', '合肥市', '蜀山区']


def login():
    return '''() => {
        xtkq('1');
    }'''


def submit():
    return f'''() => {{
        function getElementByXpath(path) {{
            return document.evaluate(path, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
        }}
        $('#dqszdmc').val('{''.join(REGION_NAME)}');
        $('#dqszddm').val('{REGION_CODE[-1]}');
        getElementByXpath("//dl/dd[@lay-value='健康']").click();
    }}'''


if __name__ == '__main__':
    print(login())
    print(submit())
