import datetime
import email
import imaplib
import os
import re
import smtplib
import time
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from urllib.parse import unquote
import requests
from bs4 import BeautifulSoup
from kairos import tools
from tv import tv

# -------------------------------------------------
#
# Utility to read email from Gmail Using Python
#
# ------------------------------------------------

BASE_DIR = r"" + os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CURRENT_DIR = os.path.curdir

log = tools.log
log.setLevel(20)
config = tools.get_config(CURRENT_DIR)
log.setLevel(config.getint('logging', 'level'))

uid = str(config.get('mail', 'uid'))
pwd = str(config.get('mail', 'pwd'))
imap_server = config.get("mail", "imap_server")
imap_port = 993
smtp_server = config.get("mail", "smtp_server")
smtp_port = 465

charts = dict()
# watchlists_dir = 'watchlists'
# watchlists_dir = os.path.join(CURRENT_DIR, watchlists_dir)
# if not os.path.exists(watchlists_dir):
#     # noinspection PyBroadException
#     try:
#         os.mkdir(watchlists_dir)
#     except Exception as watchlist_dir_error:
#         log.exception(watchlist_dir_error)
#         watchlists_dir = ''
#
# watchlist_dir = os.path.join(watchlists_dir, datetime.datetime.today().strftime('%Y%m%d'))
# if os.path.exists(watchlists_dir) and not os.path.exists(watchlist_dir):
#     # noinspection PyBroadException
#     try:
#         os.mkdir(watchlists_dir)
#     except Exception as watchlist_dir_error:
#         log.exception(watchlist_dir_error)
#         watchlists_dir = ''
#
#         os.mkdir(watchlist_dir)


def create_browser():
    return tv.create_browser()


def destroy_browser(browser):
    tv.destroy_browser(browser)


def login(browser):
    tv.login(browser)


def take_screenshot(browser, symbol, interval, retry_number=0):
    return tv.take_screenshot(browser, symbol, interval, retry_number)


def import_watchlist(browser, filepath):
    return tv.import_watchlist(browser, filepath)


def process_data(data, browser):
    for response_part in data:
        if isinstance(response_part, tuple):
            msg = email.message_from_string(response_part[1].decode('utf-8'))
            email_subject = str(msg['subject'])
            if email_subject.find('TradingView Alert') >= 0:
                log.info('Processing: ' + msg['date'] + ' - ' + email_subject)
                # get email body
                if msg.is_multipart():
                    for part in msg.walk():
                        ctype = part.get_content_type()
                        cdispo = str(part.get('Content-Disposition'))
                        # only use parts that are text/plain and not an attachment
                        if ctype == 'text/plain' and 'attachment' not in cdispo:
                            process_body(part, browser)
                            break
                else:
                    process_body(msg, browser)


def process_body(msg, browser):
    try:
        url = ''
        screenshot_url = ''
        date = msg['date']
        body = msg.get_payload()
        soup = BeautifulSoup(body, features="lxml")
        links = soup.find_all('a', href=True)
        screenshot_charts = []

        tv_generated_url = ''
        for link in links:
            if link['href'].startswith('https://www.tradingview.com/chart/?') and tv_generated_url == '':
                tv_generated_url = link['href']
            if link['href'].startswith('https://www.tradingview.com/chart/') and url == '':
                # first chart found that is generated by Kairos should be the url to the chart, either %CHART or from include_screenshots_of_charts (see _example.yaml)
                url = link['href']
            elif link['href'].startswith('https://www.tradingview.com/x/'):
                screenshot_url = link['href']
        if url == '':
            url = tv_generated_url

        # search_screenshots =
        match = re.search("screenshots_to_include: \\[(.*)\\]", body)
        if match:
            screenshot_charts = match.group(1).split(',')
            log.debug('charts to include:' + str(screenshot_charts))

        log.debug("chart's url: " + url)
        if url == '':
            return False

        symbol = ''
        match = re.search("\\w+[%3A|:]\\w+$", url, re.M)
        try:
            symbol = match.group(0)
            symbol = symbol.replace('%3A', ':')
        except re.error as match_error:
            log.exception(match_error)
        for script in soup(["script", "style"]):
            script.extract()  # rip it out

        text = soup.get_text()
        lines = (line.strip() for line in text.splitlines())  # break into lines and remove leading and trailing space on each
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))  # break multi-headlines into a line each
        # drop blank lines
        j = 0
        alert = ''
        for chunk in chunks:
            chunk = str(chunk).replace('\u200c', '')
            chunk = str(chunk).replace('&zwn', '')
            if j == 0:
                if chunk:
                    alert = str(chunk).split(':')[1].strip()
                    j = 1
            elif not chunk:
                break
            elif str(chunk).startswith('https://www.tradingview.com/chart/'):
                url = str(chunk)
            elif str(chunk).startswith('https://www.tradingview.com/x/'):
                screenshot_url = str(chunk)
            else:
                alert += ', ' + str(chunk)
        alert = alert.replace(',,', ',')
        alert = alert.replace(':,', ':')

        interval = ''
        match = re.search("(\\d+)\\s(\\w\\w\\w)", alert)
        if match:
            interval = match.group(1)
            unit = match.group(2)
            if unit == 'day':
                interval += 'D'
            elif unit == 'wee':
                interval += 'W'
            elif unit == 'mon':
                interval += 'M'
            elif unit == 'hou':
                interval += 'H'
            elif unit == 'min':
                interval += ''

        if len(screenshot_charts) == 0:
            if screenshot_url:
                screenshot_charts.append(screenshot_url)
            else:
                screenshot_charts.append(url)

        screenshots = dict()
        filenames = dict()
        # Open the chart and make a screenshot
        if config.has_option('logging', 'screenshot_timing') and config.get('logging', 'screenshot_timing') == 'summary':
            for i in range(len(screenshot_charts)):
                screenshot_chart = unquote(screenshot_charts[i])
                # screenshot_chart = screenshot_charts[i]
                # log.info(screenshot_chart)
                browser.execute_script("window.open('" + screenshot_chart + "');")
                for handle in browser.window_handles[1:]:
                    browser.switch_to.window(handle)
                # page is loaded when we are done waiting for an clickable element
                tv.wait_and_click(browser, tv.css_selectors['btn_calendar'])
                tv.wait_and_click(browser, tv.css_selectors['btn_watchlist_menu'])
                [screenshot_url, filename] = take_screenshot(browser, symbol, interval)
                if screenshot_url != '':
                    screenshots[screenshot_chart] = screenshot_url
                if filename != '':
                    filenames[screenshot_chart] = filename
                tv.close_all_popups(browser)

        charts[url] = [symbol, alert, date, screenshots, filenames]
    except Exception as e:
        log.exception(e)


def read_mail(browser):
    # noinspection PyBroadException
    try:
        mail = imaplib.IMAP4_SSL(imap_server)
        mail.login(uid, pwd)
        result, data = mail.list()
        if result != 'OK':
            log.error(result)
            return False

        mailbox = 'inbox'
        if config.has_option('mail', 'mailbox') and config.get('mail', 'mailbox') != '':
            mailbox = str(config.get('mail', 'mailbox'))
        mail.select(mailbox)

        search_area = "UNSEEN"
        if config.has_option('mail', 'search_area') and config.get('mail', 'search_area') != '':
            search_area = str(config.get('mail', 'search_area'))
        if search_area != "UNSEEN" and config.has_option('mail', 'search_term') and config.get('mail', 'search_term') != '':
            search_term = u"" + str(config.get('mail', 'search_term'))
            log.debug('search_term: ' + search_term)
            mail.literal = search_term.encode("UTF-8")

        log.debug('search_area: ' + search_area)
        try:
            result, data = mail.search("utf-8", search_area)
            mail_ids = data[0]
            id_list = mail_ids.split()
            if len(id_list) == 0:
                log.info('No mail to process')
            else:
                for mail_id in id_list:
                    result, data = mail.fetch(mail_id, '(RFC822)')
                    try:
                        process_data(data, browser)
                    except Exception as e:
                        log.exception(e)

        except imaplib.IMAP4.error as mail_error:
            log.error("Search failed. Please verify you have a correct search_term and search_area defined.")
            log.exception(mail_error)

        mail.close()
        mail.logout()
    except Exception:
        log.debug('Unable')
        # log.exception(e)


def create_watchlist(csv):
    filepath = ''
    if config.has_option('logging', 'watchlist_path'):
        watchlist_dir = config.get('logging', 'watchlist_path')
        if watchlist_dir != '':
            if not os.path.exists(watchlist_dir):
                # noinspection PyBroadException
                try:
                    os.mkdir(watchlist_dir)
                except Exception as e:
                    log.info('No watchlist directory specified or unable to create it.')
                    log.exception(e)

            if os.path.exists(watchlist_dir):
                filename = datetime.datetime.today().strftime('%Y-%m-%d_%H%M') + '.txt'
                filepath = os.path.join(watchlist_dir, filename)
                f = open(filepath, "w")
                f.write(csv)
                f.close()

    return filepath


def send_mail(browser, webhooks=True, watchlist=True):

    msg = MIMEMultipart('alternative')
    msg['Subject'] = "TradingView Alert Summary"
    msg['From'] = uid
    msg['To'] = uid
    text = ''
    list_html = ''
    html = '<html><body>'
    csv = ''

    count = 0
    if config.has_option('mail', 'format') and config.get('mail', 'format') == 'table':
        html += '<table><thead><tr><th>Date</th><th>Symbol</th><th>Alert</th><th>Screenshot</th><th>Chart</th></tr></thead><tbody>'

    for url in charts:
        symbol = charts[url][0]
        alert = charts[url][1]
        date = charts[url][2]
        screenshots = charts[url][3]
        filenames = []
        if len(charts[url]) >= 4:
            filenames = charts[url][4]

        if config.has_option('mail', 'format') and config.get('mail', 'format') == 'table':
            html += generate_table_row(date, symbol, alert, screenshots, url)
        else:
            list_html += generate_list_entry(msg, alert, screenshots, filenames, url, count)

        text += generate_text(date, symbol, alert, screenshots, url)
        if webhooks:
            send_webhooks(date, symbol, alert, screenshots, url)
        if csv == '':
            csv += symbol
        else:
            csv += ',' + symbol
        count += 1

    if config.has_option('mail', 'format') and config.get('mail', 'format') == 'table':
        html += '</tbody></tfooter><tr><td>Number of alerts:' + str(count) + '</td></tr></tfooter></table></body></html>'
    else:
        html += '<h2>TradingView Alert Summary</h2><h3>Number of signals: ' + str(count) + '</h3>' + list_html + '</body></html>'

    msg.attach(MIMEText(text, 'plain'))
    msg.attach(MIMEText(html, 'html'))
    server = smtplib.SMTP_SSL(smtp_server, smtp_port)
    server.login(uid, pwd)
    server.sendmail(uid, uid, msg.as_string())
    log.info("Mail send")
    server.quit()

    if watchlist:
        filepath = create_watchlist(csv)
        filepath = os.path.join(os.getcwd(), filepath)
        log.debug('watchlist ' + filepath + ' created')
        import_watchlist(browser, filepath)


def generate_text(date, symbol, alert, screenshots, url):
    result = url + "\n" + alert + "\n" + symbol + "\n" + date + "\n"
    for chart in screenshots:
        result += screenshots[chart] + "\n"
    return result


def generate_list_entry(msg, alert, screenshots, filenames, url, count):
    result = '<hr><h3>' + alert + '</h3><h4>Alert generated on chart: <a href="' + url + '">' + url + '<a></h4>'
    if len(screenshots) > 0:
        for chart in screenshots:
            result += '<p><a href="' + chart + '"><img src="' + screenshots[chart] + '"/></a><br/><a href="'+screenshots[chart]+'">' + screenshots[chart] + '</a></p>'
    elif len(filenames) > 0:
        for chart in filenames:
            try:
                screenshot_id = str(count + 1)
                fp = open(filenames[chart], 'rb')
                msgImage = MIMEImage(fp.read())
                fp.close()
                msgImage.add_header('Content-ID', '<screenshot' + screenshot_id + '>')
                msg.attach(msgImage)
                result += '<p><a href="' + chart + '"><img src="cid:screenshot' + screenshot_id + '"/></a><br/>' + filenames[chart] + '</p>'
            except Exception as send_mail_error:
                log.exception(send_mail_error)
                result += '<p><a href="' + url + '">Error embedding screenshot: ' + filenames[chart] + '</a><br/>' + filenames[chart] + '</p>'
    return result


def generate_table_row(date, symbol, alert, screenshots, url):
    result = '<tr><td>' + date + '</td><td>' + symbol + '</td><td>' + alert + '</td><td>'
    for chart in screenshots:
        result += '<a href="' + screenshots[chart] + '">' + screenshots[chart] + '</a>'
    result += '</td><td>' + '<a href="' + url + '">' + url + '</a>' + '</td></tr>'
    return result


def send_webhooks(date, symbol, alert, screenshots, url):
    result = False
    if config.has_option('webhooks', 'search_criteria') and config.has_option('webhooks', 'webhook'):
        search_criteria = config.getlist('webhooks', 'search_criteria')
        webhooks = config.getlist('webhooks', 'webhook')

        for i in range(len(search_criteria)):
            if str(alert).index(str(search_criteria[i])) >= 0:
                for j in range(len(webhooks)):
                    if webhooks[j]:
                        # result = [500, 'Internal Server Error; search_criteria: ' + str(search_criteria[i]) + '; webhook: ' + str(webhooks[j])]
                        screenshot = ''
                        for chart in screenshots:
                            if screenshot == '':
                                screenshot = screenshots[chart]
                        json = {'date': date, 'symbol': symbol, 'alert': alert, 'chart_url': url, 'screenshot_url': screenshot, 'screenshots': screenshots}
                        log.debug(json)
                        r = requests.post(str(webhooks[j]), json=json)
                        # unfortunately, we cannot always send a raw image (e.g. zapier)
                        # elif filename:
                        #     screenshot_bytestream = ''
                        #     try:
                        #         fp = open(filename, 'rb')
                        #         screenshot_bytestream = MIMEImage(fp.read())
                        #         fp.close()
                        #     except Exception as send_webhook_error:
                        #         log.exception(send_webhook_error)
                        #     r = requests.post(webhook_url, json={'date': date, 'symbol': symbol, 'alert': alert, 'chart_url': url, 'screenshot_url': screenshot, 'screenshot_bytestream': screenshot_bytestream})
                        result = [r.status_code, r.reason]
                        if result[0] != 200:
                            log.warn(str(result[0]) + ' ' + str(result[1]))
    return result


def run(delay):
    log.info("Generating summary mail with a delay of " + str(delay) + " minutes.")
    time.sleep(delay*60)
    browser = create_browser()
    login(browser)
    read_mail(browser)
    if len(charts) > 0:
        send_mail(browser)
    destroy_browser(browser)
