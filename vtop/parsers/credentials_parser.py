from bs4 import BeautifulSoup

def parse_credentials(html_content):
    """
    Parses the VTOP Student Credentials HTML response.
    Returns a dictionary with 'accounts' and 'exams' lists.
    """
    if not html_content:
        return {'accounts': [], 'exams': []}

    soup = BeautifulSoup(html_content, 'html.parser')
    data = {'accounts': [], 'exams': []}
    
    table = soup.find('table', class_='customTable')
    if not table:
        return data

    rows = table.find_all('tr', class_='tableContent')
    
    for row in rows:
        cells = row.find_all('td')
        # Expecting at least: Account, Username, Password, URL, Venue&Date, Seat
        if len(cells) >= 3:
            account = cells[0].get_text(strip=True)
            username = cells[1].get_text(strip=True)
            password = cells[2].get_text(strip=True)
            
            url = "#"
            if len(cells) > 3:
                link = cells[3].find('a')
                if link:
                    url = link.get('href')
                else:
                    txt = cells[3].get_text(strip=True)
                    if txt.startswith('http'): url = txt

            venue_date = "-"
            seat = "-"
            if len(cells) > 4:
                venue_date = cells[4].get_text(strip=True)
            if len(cells) > 5:
                seat = cells[5].get_text(strip=True)

            entry = {
                'account': account,
                'username': username,
                'password': password,
                'url': url,
                'venue_date': venue_date,
                'seat': seat
            }

            # Distinguish based on Venue/Date presence or "EXAM" keyword
            if venue_date and venue_date != '-' and venue_date != '':
                data['exams'].append(entry)
            else:
                data['accounts'].append(entry)
            
    return data