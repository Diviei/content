import email.utils
from time import mktime

import feedparser

from CommonServerPython import *
from bs4 import BeautifulSoup

HTML_TAGS = ['p', 'table', 'ul', 'ol', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6']


class Client(BaseClient):
    """Client for RSS Feed - gets Reports from the website
    Attributes:
        server_url(str): The RSS URL.
        use_ssl: Whether to use ssl.
        proxy(str): Use system proxy.
    """

    def __init__(self, server_url, use_ssl, proxy, feed_tags, tlp_color, content_max_size=45):
        super().__init__(base_url=server_url, proxy=proxy, verify=use_ssl)
        self.feed_tags = feed_tags
        self.tlp_color = tlp_color
        self.content_max_size = content_max_size * 1000
        self.parsed_indicators = []
        self.feed_data = None
        self.feed_response = self.request_feed_url()

    def request_feed_url(self):
        return self._http_request(method='GET', resp_type='response')

    def create_indicators_from_response(self):
        parsed_indicators: list = []
        if not self.feed_data:
            raise DemistoException(f"Could not parse feed data {self._base_url}")

        for indicator in reversed(self.feed_data.entries):
            publications = []
            if indicator:
                published = email.utils.parsedate(indicator.published)
                if published:
                    published_iso = datetime.fromtimestamp(mktime(published)).isoformat()
                    publications.append({
                        'timestamp': indicator.get('published'),
                        'link': indicator.get('link'),
                        'source': self._base_url,
                        'title': indicator.get('title')
                    })
                    text = self.get_url_content(indicator.get('link'))
                    indicator_obj = {
                        "type": 'Report',
                        "value": indicator.get('title').replace(',', ''),  # Remove comma because the script of create
                        # relationship includes that as a list of titles.
                        "rawJSON": {'value': indicator, 'type': 'Report', "firstseenbysource": published_iso},
                        "fields": {
                            'rawcontent': text,
                            'publications': publications,
                            'description': indicator.get('summary'),
                            'tags': self.feed_tags,
                        }
                    }
                    if self.tlp_color:
                        indicator_obj['fields']['trafficlightprotocol'] = self.tlp_color

                parsed_indicators.append(indicator_obj)

        return parsed_indicators

    def get_url_content(self, link: str):
        """Returns the link content only from the relevant tags (listed on HTML_TAGS). For better performance - if the
         extracted content is bigger than "content_max_size" we trim him"""

        response_url = self._http_request(method='GET', full_url=link, resp_type='str')
        report_content = 'This is a dumped content of the article. Use the link under Publications field to read ' \
                         'the full article. \n\n'
        soup = BeautifulSoup(response_url.text, "html.parser")
        for tag in soup.find_all():
            if tag.name in HTML_TAGS:
                for string in tag.stripped_strings:
                    report_content += ' ' + string
        if len(report_content.encode('utf-8')) > self.content_max_size:  # Ensure report_content does not exceed the
            # indicator size limit (~50KB)
            report_content = report_content.encode('utf-8')[:self.content_max_size].decode('utf-8')
        return report_content

    def fetch_indicators(self):
        self.feed_data = feedparser.parse(self.feed_response.text)
        self.parsed_indicators = self.create_indicators_from_response()


def get_indicators(client: Client, args: dict) -> CommandResults:
    limit = int(args.get('limit', 10))
    parsed_indicators = client.parsed_indicators[:limit]
    parsed_for_hr = [{'Title': indicator.get('value'),
                      'Link': indicator.get('fields').get('publications')[0].get('link'),
                      'Type': indicator.get('type')}
                     for indicator in parsed_indicators]
    headers = ['Title', 'Link', 'Type']
    hr_ = tableToMarkdown(name='RSS Feed:', t=parsed_for_hr, headers=headers)
    return CommandResults(
        readable_output=hr_,
        raw_response=client.feed_data
    )


def main():
    params = demisto.params()
    server_url = params.get('server_url')
    command = demisto.command()
    demisto.info(f'Command being called is {command}')
    try:
        client = Client(server_url=server_url,
                        use_ssl=not params.get('insecure', False),
                        proxy=params.get('proxy'),
                        feed_tags=argToList(params.get('feedTags')),
                        tlp_color=params.get('tlp_color'),
                        content_max_size=int(params.get('max_size', '45')))

        if command == 'test-module':
            if 'html' in client.feed_response.headers['content-type']:
                raise DemistoException(f'{server_url} is not rss feed url. Try look for a url containing \'feed\' '
                                       f'prefix or suffix.')
            else:
                return_results("ok")

        elif command == 'rss-get-indicators':
            client.fetch_indicators()
            return_results(get_indicators(client, demisto.args()))

        elif command == 'fetch-indicators':
            client.fetch_indicators()
            for iter_ in batch(client.parsed_indicators, batch_size=2000):
                demisto.createIndicators(iter_)
        else:
            raise NotImplementedError(f'Command {command} is not implemented.')

    except ValueError:
        raise DemistoException("Article content max size must be a number, for example 50.")
    except Exception as err:
        demisto.error(traceback.format_exc())  # print the traceback
        return_error(f"Failed to execute {command} command.\nError:\n{str(err)}")


if __name__ in ('builtin__', 'builtins', '__main__'):
    main()
