#!/usr/bin/python
from encodings.utf_8 import encode
from mechanize._form import ControlNotFoundError

__author__ = 'Alexander Ortner'
__version__ = '1.0beta'
__date__    = '2012-04-01'

"""
SocialSnapshot.py
         This file is part of SocialSnapshot.

    Facebook Scraper written by Alexander Ortner e0925455@student.tuwien.ac.at, Vienna University of Technology

    Usage:
        python SocialSnapshot.py -u <email> -p <password>
        python SocialSnapshot.py -c <cookie string>
        optional parameter: -a <user agent string>

    * logs into Facebook account (credentials or cookie information)
    * starts separate process to connect Graph-App, allow full access and remove Graph App when done
        -> redoes the first two steps as long as the server keeps destroying our session (which sometimes happens)
    * simultaneously: iterates over list of friends and saves contact information for each friend in csv file
"""

import csv
import json
import mechanize
import sys
import re
import urllib
import getopt
import cookielib
from BeautifulSoup import BeautifulSoup
from BSXPath import BSXPathEvaluator,XPathResult
from multiprocessing import Process
import codecs
import logging
import random
import socket
from urllib2 import HTTPError, URLError
import cStringIO
from mechanize._mechanize import FormNotFoundError
import time


usr=pwd=cookie=uag=browser=None
debug = False
stages = ["[LOGIN]", "[GRAPH]", "[FETCH]"]
logger = None
tries=0

app_id=172373282779700 #Facebook App-ID of 'Social Snapshot App'
app_url='http://crunch0r.ifs.tuwien.ac.at/SocialSnapshot/php/' #url for app that is to be connected with FB
app_welcome_string= "Fetching your Facebook account data..." #String that identifies that app is connected with FB



def main():
    global usr, pwd, cookie, uag, debug, browser, logger

    logger = initLogger()

    letters = 'u:p:c:a:' #defining allowed letters
    keywords = ['user=', 'password=', 'cookie=', 'user-agent'] #defining keywords for letters
    opts, extraParams = getopt.getopt(sys.argv[1:], letters,keywords) #set options an keywords

    #handle passed params
    for option,param in opts:
        if option in ['-u','--user']:
            usr = param
        elif option in ['-p','--password']:
            pwd = param
        elif option in ['-c','--cookie']:
            cookie = param
        elif option in ['-a','--user-agent']:
            uag = param

    if (usr is None or pwd is None) and cookie is None:
        print 'you need to pass username and password or a cookie string! \n exiting...'
        print '\nYou have provided the following parameters:'
        print '\toptions:',opts
        print '\textra parameters:',extraParams
        sys.exit(1)

    logger.info('##################################################\n' \
          '# User      : %s \n' \
          '# Password  : %s \n' \
          '# Cookie    : %s \n' \
          '# User-Agent: %s \n' \
          '##################################################'% (usr,pwd,cookie,uag))

    #if user did not provide a user agent
    uag = getUAG()  #generate one of the user agents allowed by facebook
    if uag is None:
        logger.info('setting user agent to %s' %uag)

    #login
    login(usr,pwd,cookie)

    #initialize process for facebook-app connection and execution
    p = Process(target=connectGraphApp, args=(cookie,uag))
    p.start()

    #crawl through friends and save in csv
    collectFriendsEmails()

""" login (username, password, cookie)
    creates a browser instance and performs facebook login
"""
def login(usr,pwd,cooki):
    global uag, browser, cookie, logger
    headers = []
    logger.info("%s launching login procedure..." % stages[0])

    #initialize browser
    browser = mechanize.Browser()
    browser.set_handle_robots(False) #ignore robots.txt
    browser.set_cookiejar(cookielib.LWPCookieJar()) #set cookieJAR to enable cookie support
    browser.redirection_limit=20
    browser.set_debug_redirects(True)


    headers.append(('User-agent', uag))
    browser.addheaders = headers

    #IF USER AND PWD VARIABLE SET
    if usr is not None and pwd is not None:
        #get post form data
        response = browser.open("http://m.facebook.com/index.php")
        match = re.search('name=\'post_form_id\' value=\'(\w+)\'', response.read())
        #post_form_id = match.group(1)
        post_form_id = ''
        if debug: print 'post_form_id: %s' % post_form_id

        #set POST data
        data = urllib.urlencode({
            'lsd'               : '',
            'post_form_id'      : post_form_id,
            'charset_test'      : urllib.unquote_plus('%E2%82%AC%2C%C2%B4%2C%E2%82%AC%2C%C2%B4%2C%E6%B0%B4%2C%D0%94%2C%D0%84'),
            'email'             : usr,
            'pass'              : pwd,
            'login'             : 'Login'
        })


        #Facebook Login
        logger.info('[LOGIN] logging in as ' + usr)
        try:
            res = browser.open('http://www.facebook.com/login.php?m=m&refsrc=http%3A%2F%2Fm.facebook.com%2Findex.php&refid=8', data,timeout=10.0)
        except:
            logger.error("TIME OUT at login.")

    #else add cookie to header
    elif cooki is not None:
        headers.append(('Cookie', cooki))
        browser.addheaders = headers

    #save current cookie information in global cookie var (cookie information of browser session is needed for connectGraph())
    if cookie is None:
        cookie=''
        for c in browser._ua_handlers['_cookies'].cookiejar:
            cookie+=c.name+'='+c.value+';'

    if isBrowserLoggedIn(browser): #check if logged in
        logger.info("%s login successful!" % stages[0])
        return cookie
    else:
        logger.error("%s login failed! \n exiting" % stages[0])
        exit(1)

    print "###########################################################"


def isBrowserLoggedIn(browser):
    """ isBrowserLoggedIn(browser object)
    checks if user is logged in by opening facebook.com
    """
    res = browser.open('http://www.facebook.com/')
    match = re.search('loggedout_menubar_container', res.read()) #if loginpage visible(-> logged out)
    if match:
        return False
    else:
        return True


def isLoggedIn(lastResponse):
    """ isLoggedIn(lastResponse)
    checks if user is logged in by looking at html contents of the passed parameter (should be response.read() of last response)
    returns True if logged in
    """
    match = re.search('loggedout_menubar_container', lastResponse) #if loginpage visible(-> logged out)
    if match:
        return False
    else:
        return True


def launchCrawlingApp(html):
    """launchCrawlingApp(html)
        this function is specific to the SocialSnapshot Facebook App!
        clicks the continue link in given parameter 'html', which should be the result of a response.read()
    """
    print "-----------------------------launchCrawling"
    global browser, logger
#look for continue-link and click it
    try:
        link = re.search('class=\'continue\' href=\'(.*?)\'',html).group(1)
        link = 'http://crunch0r.ifs.tuwien.ac.at%s' % link
        print '%s graph app is crawling :D' % stages[1]

        res0 = browser.open(link) #click CONTINUE
        html = res0.read()
        f = open('continue','w')
        f.write(BeautifulSoup(html).prettify())
        f.write(html)

        print '%s graph app has finished crawling ;)' % stages[1]

    except:
        print "UNEXPECTED ERROR: ",sys.exc_info()[0]


def connectGraphApp(cookie,uag):
    """

    """
    global debug, app_id, app_url, browser, app_welcome_string, logger, tries

    if tries==0:
        logger = initLogger()
    tries+=1

    logger.info("%s launching CONNECTION TO GRAPH APP. This is try number: %d" % (stages[1], tries))

    if browser is None:
        browser=mechanize.Browser()
        browser.set_cookiejar(mechanize.CookieJar()) #set cookieJAR to enable cookie support
        browser.set_handle_robots(False) #ignore robots.txt
        browser.redirection_limit=1000
        browser.set_debug_redirects(True)

    headers=[]
    headers.append(('Cookie', cookie))
    headers.append(('User-agent', uag))
    browser.addheaders = headers

    try2connect=True
    while try2connect:
        try:
        #connect with Graph app
            res = browser.open('http://www.facebook.com/login.php?api_key='+str(app_id)+'' \
                                                                '&cancel_url='+str(app_url)+
                                                                '&display=page&fbconnect=1' \
                                                                '&next='+str(app_url)+ \
                                                                '&return_session=1&session_version=3&v=1.0' \
                                                              '&req_perms=email%2Cread_insights%2Cread_stream%2Cread_mailbox%2Cuser_about_me%2Cuser_activities%2Cuser_birthday%2Cuser_education_history%2Cuser_events%2Cuser_groups%2Cuser_hometown%2Cuser_interests%2Cuser_likes%2Cuser_location%2Cuser_notes%2Cuser_online_presence%2Cuser_photo_video_tags%2Cuser_photos%2Cuser_relationships%2Cuser_religion_politics%2Cuser_status%2Cuser_videos%2Cuser_website%2Cuser_work_history%2Cread_friendlists%2Cread_requests%2Cfriends_about_me%2Cfriends_activities%2Cfriends_birthday%2Cfriends_education_history%2Cfriends_events%2Cfriends_groups%2Cfriends_hometown%2Cfriends_interests%2Cfriends_likes%2Cfriends_location%2Cfriends_notes%2Cfriends_online_presence%2Cfriends_photo_video_tags%2Cfriends_photos%2Cfriends_relationships%2Cfriends_religion_politics%2Cfriends_status%2Cfriends_videos%2Cfriends_website%2Cfriends_work_history%2Coffline_access', timeout=5.0)
            html = res.read()
        except URLError:
            logger.error('%s a URL TIMEOUT occured while trying to connect with facebook app' % stages[1])
        except:
            logger.error( '%s an unknown error occured while fetching data for %s' % (stages[1]))
            print '\terror:',sys.exc_info()[0]

        if isLoggedIn(html):
            try2connect=False
        else:
            logger.warning('%s we have lost our session. lets login again.' % stages[1])
            login(None,None,cookie)


    f = open('allowPage','w')
    f.write(BeautifulSoup(html).prettify())

    if re.search(app_welcome_string,html): #if "al ready fetching"-page shows up
        #logging.warning("%s graph app is already allowed!" % stages[1])
        print "%s graph app is already allowed!" % stages[1]
        #launchCrawlingApp(html) #launch application (NOTE: this is specific to facebook-app)
    elif re.search('grant_required_clicked',html): #old: grant_clicked
        logger.info("%s starting app allowance procedure..." % stages[1])

        #select form to allow full access of application
        try:
            browser.select_form(predicate=lambda f: 'id' in f.attrs and f.attrs['id'] == 'uiserver_form')
            #print browser.form
        except FormNotFoundError:
            logger.error('%s RATS! Facebook may be blocking our continuous requests \n our user agent was: %s \n trying again...' % (stages[1],uag))

            connectGraphApp(cookie,getUAG())
            return

        #print '--------------start first--------------'
        #press "allow"
        try:
            res = browser.submit(name='grant_required_clicked')

            html = res.read()
            f = open('afterSubmit', 'w')
            f.write(BeautifulSoup(html).prettify())
        except HTTPError:
            logger.error('%s Error occured while trying to connect app. \n trying again...' % stages[1])

            connectGraphApp(cookie,getUAG())
            return
        except ControlNotFoundError:
            logger.error('%s expected button to grant access was not found and could not be clicked' % stages[1])
            return
        #print '--------------end first--------------'

    if re.search('grant_clicked',html):
        #select form to allow full access of application
        try:
            browser.select_form(predicate=lambda f: 'id' in f.attrs and f.attrs['id'] == 'uiserver_form')
            #print browser.form
        except FormNotFoundError:
            logger.error('%s RATS! Facebook may be blocking our continuous requests \n our user agent was: %s \n trying again...' % (stages[1],uag))
            connectGraphApp(cookie,getUAG())
            return

        #print '--------------start seconod--------------'
        #press "allow"
        try:
            res = browser.submit(name='grant_clicked')

            html = res.read()
            f = open('afterSubmit2', 'w')
            f.write(BeautifulSoup(html).prettify())
        except HTTPError:
            logger.error('%s Error occured while trying to connect app. \n trying again...' % stages[1])
            connectGraphApp(cookie,getUAG())
            return
        except ControlNotFoundError:
            logger.error('%s expected button to grant access was not found and could not be clicked' % stages[1])
            return

        #print '--------------end second--------------'

        #IF error div in result page
        if re.search('platform_dialog_error',html):
            logger.error("%s connection to graph app failed. (error: facebook error page appeared)" % stages[1])
            f = open('notConnected', 'w')
            f.write(BeautifulSoup(html).prettify())
        #ELSE IF 'welcome'-string (specific to app that is being connected)shows up in response
        elif re.search(app_welcome_string,html):
            logging.info('%s blimey! connection to graph app successful.' % stages[1])
            f = open('connected', 'w')
            f.write(BeautifulSoup(html).prettify())

            launchCrawlingApp(html) #launch application (NOTE: this is specific to facebook-app)

            logger.info("%s removing app from profile..." % stages[1])

            #open applications
            res = browser.open('http://www.facebook.com/settings?tab=applications')
            html=res.read()
            f = open('applications','w')
            f.write(BeautifulSoup(html).prettify())
            f.write(html)
            match = re.search('name="post_form_id" value="(\w+)"', html)
            #post_form_id = match.group(1)
            post_form_id=''

            match = re.search('name="fb_dtsg" value="(\w+)"', html)
            fb_dtsg = match.group(1)

            phstamp = generatePhstamp('remove=1&app_id=172373282779700&post_form_id=9bf40f0912e2612d28a066dad7f8c7a5&fb_dtsg=AQCIvb4n&lsd&post_form_id_source=AsyncRequest&__user=100003543241599',fb_dtsg)
            if debug: print "phstamp %s" % phstamp

            data = urllib.urlencode({
                '__user'              : 100003543241599, #TODO: GET FROM HTML!
                'app_id'              : app_id,
                'fb_dtsg'             : fb_dtsg,
                'lsd'                 : "",
                'phstamp'             : phstamp,
                'post_form_id'        : post_form_id,
                'post_form_id_source' : "AsyncRequest",
                'remove'              : 1,
                })

            #remove application from facebook account
            res = browser.open('http://wwww.facebook.com/ajax/edit_app_settings.php?__a=1', data)
        #            html = res.read()
        #            print app_id
        #            print html
        #            if re.search(app_id,html):
        #                print 'App could not be removed.'

        else:
            logger.error('%s Facebook may be blocking our continuous requests \n our user agent was: %s \n trying again...' % (stages[1],uag))
            connectGraphApp(cookie,getUAG())

    print "###########################################################"

def collectFriendsEmails():
    """collectFriendsEmails()
        uses official facebook api to get list of friends
        uses list of friends to manually access info page of each
        saves each contact information in csv
    """
    global user, debug, browser
    startTime = time.time()

    logging.info("%s launching CONTACT-DATA COLLECTION" % stages[2])
    #contacts = ["AIM","Google Talk","Windows Live Messenger","Skype","Yahoo! Messenger","Gadu-Gadu","ICQ","Yahoo Japan","QQ","NateOn","Twitter","Hyves","Orkut","Cyworld","mixi","QIP","Rediff Bol","Vkontakte", "eBuddy", "Mail.ru Agent", "Jabber"]
    #get Access Token

    res = browser.open('http://developers.facebook.com/docs/reference/api')
    html = res.read()

    print "%s fetching access token..." % stages[2]
    match = re.search('access_token=(.*?)"', html)
    acc = match.group(1)
    if debug: print 'access token: ' + acc

    # Get friend's ID
    res = browser.open('https://graph.facebook.com/me/friends?access_token=%s' % acc)
    html = res.read()
    friends = json.loads(html)

    #create csv writer
    f = open('%s.csv' % usr, 'ab')
    writer = UnicodeWriter(f)

    #writer = csv.writer(open('%s.csv' % usr, 'ab'), delimiter=';', quotechar='"', quoting=csv.QUOTE_MINIMAL)

    #for each dataset in JSON data
    for acc in friends['data']:
        friend_id = acc['id']
        friend_name = acc['name']

        #open profile url
        try:
            res = browser.open('http://m.facebook.com/profile.php?id=%s&v=info&refid=17' % friend_id,timeout=3.0)
            html = res.read()
            #        f = open('draft','w')
            #        f.write(html)

            document = BSXPathEvaluator(html)

            resume=True
            i = 1
            contact_infos = [friend_id,friend_name]
            while resume:
                #look for line in table of contact details and extra contact detail
                result = document.evaluate('//div[@id="contact"]//table//tr[%d]'%i,document,None,XPathResult.STRING_TYPE,None)
                contact_info = result.stringValue
                i+=1
                if len(contact_info)==0:
                    resume=False
                else:
                    contact_info=contact_info.replace('&#064;','@') #replace html character code
                    contact_info=contact_info.replace('%40', '@') #replace url encoding
                    if 'Website' not in contact_info:
                        contact_infos.append(contact_info) #append contact info to list of infos
            #if len(contact_infos)>2: #if contact info apart from id and name was found
            logging.info(contact_infos)
            writer.writerow(contact_infos) #write to csv
        except URLError as e:
            logging.warning('%s a URL TIMEOUT occured while fetching data for %s' % (stages[2],friend_name)
                            + '\terror:'+str(e))
        except socket.error as e:
            logging.warning('%s a SOCKET ERROR occured while fetching data for %s' % (stages[2],friend_name))
            print '\terror:',sys.exc_info()[0],str(e)
        except:
            print '%s an unknown error occured while fetching data for %s' % (stages[2],friend_name)
            print '\terror:',sys.exc_info()[0]

    #set end time for calculation of 'time elapsed'
    endTime = time.time()
    print 'time elapsed: %d seconds' %(endTime-startTime)
    print '%s finished collection of contact data. \n program will exit when crawling is finished...' % stages[2]


def getUAG():
    """ getUAG()
    returns a random user agent from a list of agents that are allowed by facebook
    """
    uags =  []
    uags.append('Mozilla/5.0 (Windows; U; Windows NT 6.1; tr-TR) AppleWebKit/533.20.25 (KHTML, like Gecko) Version/5.0.4 Safari/533.20.27')
    uags.append('IE 7 ? Mozilla/4.0 (compatible; MSIE 7.0; Windows NT 5.1; .NET CLR 1.1.4322; .NET CLR 2.0.50727; .NET CLR 3.0.04506.30)2011-10-16 20:20:09')
    uags.append('Opera/9.80 (Windows NT 6.1; U; en) Presto/2.10.229 Version/11.61')

    return uags[random.randint(0,len(uags)-1)] #return random user agent

def generatePhstamp(query, dtsg):
    """ generatePhstamp (query, dtsg)
        generates the phstamp-variable that is needed by facebook to verify certain requests
        uses a hidden form value and the query (only params) for calculation
        returns the phstamp
    """
    input_len=len(query)
    numeric_csrf_value=''

    for i in range(len(dtsg)):
        numeric_csrf_value+=str(ord(dtsg[i]));

    return '1%s%d' % (numeric_csrf_value, input_len);

def initLogger():
    """ initLogger()
        initialises logger
    """
    #initialiaze logger
    logging.basicConfig(filename='social_snapshot.log', format='%(levelname)s:%(message)s',level=logging.INFO)

    #initialize and configure logger for mechanize
    #logger = logging.getLogger("mechanize") #output mechanize redirects
    logger = logging.getLogger()
    logger.addHandler(logging.StreamHandler(sys.stdout))
    logger.setLevel(logging.INFO)
    return logger

def craftAllowanceForm(allowPage):
    """ craftAllowanceForm(allowPage)
        extracts form data from given html data and sends request for app allowance with forged post data to the server
        returns the response
    """
    html = allowPage
    #Get form values for POST data
#        match = re.search('name="post_form_id" value="(\w+)"', html)
#        post_form_id = match.group(1)
#        post_form_id = ''
#        if debug: print "post_form_id "+post_form_id

    #print "logged in:",isLoggedIn(browser)
    match = re.search('name="fb_dtsg" value="(\w+)"', html)
    fb_dtsg = match.group(1)
    if debug: print "fb_dtsg "+fb_dtsg

    match = re.search('name="perms" value="(.*?)"', html)
    perms = match.group(1)
    if debug: print "perms " + perms

    match = re.search('name="new_perms" value="(.*?)"', html)
    new_perms = match.group(1)
    if debug: print "new_perms " + new_perms

    match = re.search('name="orig_perms" value="(.*?)"', html)
    orig_perms = match.group(1)
    if debug: print "orig_perms " + orig_perms

    match = re.search('name="return_session" value="(.*?)"', html)
    return_session = match.group(1)
    if debug: print "return_session " + return_session

    match = re.search('name="session_version" value="(.*?)"', html)
    session_version = match.group(1)
    if debug: print "session_version " + session_version

    app_id = 172373282779700
    display = "page"
    redirect_uri = "http://crunch0r.ifs.tuwien.ac.at/SocialSnapshot/php/"
    cancel_url = "http://crunch0r.ifs.tuwien.ac.at/SocialSnapshot/php/"
    locale = "de_DE"
    fbconnect = 1
    canvas = 0
    legacy_return = 1
    from_post = 1
    uiserv_method = "permissions.request"
    email_type = "contact_email"
    grant_clicked = " "

    #set POST data
    data = urllib.urlencode({
        #'post_form_id'      : post_form_id,
        'fb_dtsg'           : fb_dtsg,
        'perms'             : perms,
        'new_perms'         : new_perms,
        'orig_perms'        : orig_perms,
        'return_session'    : return_session,
        'session_version'   : session_version,
        'app_id'            : app_id,
        'display'           : display,
        'redirect_uri'      : '',#redirect_uri
        'cancel_url'        : cancel_url,
        'locale'            : locale,
        'fbconnect'         : fbconnect,
        'canvas'            : canvas,
        'legacy_return'     : legacy_return,
        'from_post'         : from_post,
        '__uiserv_method'   : uiserv_method,
        'grant_clicked'     : grant_clicked,
        'GdpEmailBucket_grantEmailType' : email_type,
        'dubstep'           : 1
    })

    if debug: print "POST DATA:\n"+data

    #press "allow"
    res = browser.open('http://www.facebook.com/connect/uiserver.php', data)
    return res

class UnicodeWriter:
    """
    A CSV writer which will write rows to CSV file "f",
    which is encoded in the given encoding.

    This code was taken from the official python documentation!
    """

    def __init__(self, f, dialect=csv.excel, encoding="utf-8", **kwds):
        # Redirect output to a queue
        self.queue = cStringIO.StringIO()
        self.writer = csv.writer(self.queue, dialect=dialect, delimiter=';',**kwds)
        self.stream = f
        self.encoder = codecs.getincrementalencoder(encoding)()

    def writerow(self, row):
        self.writer.writerow([s.encode("utf-8") for s in row])
        # Fetch UTF-8 output from the queue ...
        data = self.queue.getvalue()
        data = data.decode("utf-8")
        # ... and reencode it into the target encoding
        data = self.encoder.encode(data)
        # write to the target stream
        self.stream.write(data)
        # empty queue
        self.queue.truncate(0)

    def writerows(self, rows):
        for row in rows:
            self.writerow(row)

if __name__ == '__main__':
    main()