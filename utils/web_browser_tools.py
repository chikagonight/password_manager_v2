import webbrowser

class WebBrowserTools:
    def __init__(self, url_link):
        self.url_link = url_link

    def open_link_in_browser(self):
        webbrowser.open(self.url_link)