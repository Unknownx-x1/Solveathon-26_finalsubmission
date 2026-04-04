from bs4 import BeautifulSoup

def parse_credentials(html_content):
    """
    Parses the VTOP Student Credentials HTML response into a dictionary.
    """
    if not html_content:
        return {'accounts': [], 'exams': []}

    soup = BeautifulSoup(html_content, 'html.parser')
    data = {'accounts': [], 'exams': []}
    
    # Target the specific table class used by VTOP
    table = soup.find('table', class_='customTable')
    if not table:
        return data

    rows = table.find_all('tr', class_='tableContent')
    
    for row in rows:
        cells = row.find_all('td')
        # Expecting: Account, Username, Password, URL, Venue/Date, Seat
        if len(cells) >= 3:
            entry = {
                'account': cells[0].get_text(strip=True),
                'username': cells[1].get_text(strip=True),
                'password': cells[2].get_text(strip=True),
                'url': cells[3].find('a').get('href') if cells[3].find('a') else "#",
                'venue_date': cells[4].get_text(strip=True) if len(cells) > 4 else "-",
                'seat': cells[5].get_text(strip=True) if len(cells) > 5 else "-"
            }

            # If a venue/date exists, it is categorized as an exam credential
            if entry['venue_date'] and entry['venue_date'] != '-':
                data['exams'].append(entry)
            else:
                data['accounts'].append(entry)
            
    return data