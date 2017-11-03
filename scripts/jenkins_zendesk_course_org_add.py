#!/Library/Frameworks/Python.framework/Versions/3.5/bin/python3 -tt
# Author Matt
# Created on 6/21/2016

# Automation to look at course field in Zendesk and add the course org/institution
# to the ticket

import os
import pymysql
import zenpy
import vertica_python
import time
import fnmatch
import smtplib
import mimetypes
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

#hack to find the enterprise tickets and add the enterprise_customer_name
def enterprise_ticket_search(api_connection, lms_conn):
  enterprise_sql = "select ep.name from enterprise_enterprisecustomeruser eu, " \
                        "enterprise_enterprisecustomer ep, auth_user au " \
                        "where au.id = eu.user_id and eu.enterprise_customer_id = ep.uuid " \
                        "and au.email = 'EMAILADDRESS'"
  lms_cur = lms_conn.cursor()     
  print ('Searching for Enterprise tickets....')                 
  for ticket in api_connection.search(status_less_than = 'closed'):
    if 'closed_by_merge' in ticket.tags or ticket.requester.email == 'service@paypal.com': #hacky bug fix
      pass
    else:
      lms_cur.execute(enterprise_sql.replace('EMAILADDRESS', ticket.requester.email))
      enterprise_name = lms_cur.fetchone()
      if enterprise_name:
        for field in ticket.custom_fields:
          if field['id'] == 77417128: #enterprise_customer_name Zendesk field ID
            if field['value']:
              pass
            else:  
              field['value'] = enterprise_name[0]
              ticket.tags.append('enterprise_learner')
              print (str(ticket.id) + ' ticket will add Enterprise name of ' + enterprise_name[0])
              api_connection.tickets.update(ticket)
  lms_cur.close()
        

# Finds all the not closed tickets and checks if the course field exists
def ticket_search(api_connection):
  print ('Searching for Zendesk tickets......')
  ticket_results = []
  for ticket in api_connection.search(status_less_than = 'closed'):
    # Add logic so that it ignores tickets that have a partner_ tag
    filtered = fnmatch.filter(ticket.tags, 'partner_*')
    if filtered or 'closed_by_merge' in ticket.tags: #for some reason the search finds closed_by_merge tickets
      pass
    elif 'whitelabel_harvardxplus' in ticket.tags:
      ticket_results.append({'ticketid': ticket.id, 'course': field['value'], 'tickobj': ticket})
    else:  
      for field in ticket.custom_fields:
        if field['id'] == 27215768:
          if field['value'] and field['value'] != 'None' and field['value'] != 'none' and field['value'] != 'NONE':
            ticket_results.append({'ticketid': ticket.id, 'course': field['value'], 'tickobj': ticket})
  return ticket_results

# Checks the lms and edge databases to see if the course ID exists. puts the tickets into
# different buckets of exists, does not exist, bad format for the course ID
def course_search(tickets, lms_conn, edge_conn):
  print ('Searching for Courses......')
  course_results = []
  no_course_results = []
  bad_course_results = []
  course_org_sql = "select org from course_overviews_courseoverview where id = '"
  user_mode_sql = "select sc.mode from student_courseenrollment sc, auth_user au where au.id = sc.user_id and au.email = '"
  lms_cur = lms_conn.cursor()
  edge_cur = edge_conn.cursor()
  for ticket in tickets:
    # add sys_eng check here and if successful add ticket to course_results MITProfessionalX is org
    if ticket['course'] == 'syseng_bundle' or ticket['course'] == 'syseng_bundle_3' or ticket['course'] == 'syseng_bundle_4':
      course_results.append({'ticketid': ticket['ticketid'], 'org': 'MITxPRO', 'tickinfo': ticket})
    # check ticket['tickobj'].tags if whitelabel_harvardxplus
    elif 'whitelabel_harvardxplus' in ticket['tickobj'].tags:
      course_results.append({'ticketid': ticket['ticketid'], 'org': 'HarvardXPLUS', 'tickinfo': ticket})
    else:
      try:
        lms_cur.execute(course_org_sql + ticket['course'] + "'")
        lms_output = lms_cur.fetchone()
        if lms_output:
          if ticket['tickobj'].requester.email:
            # ADDED some enrollment check
            lms_cur.execute(user_mode_sql + ticket['tickobj'].requester.email + "' and sc.course_id = '" + ticket['course'] + "'")
            lms_user_output = lms_cur.fetchone()
            if lms_user_output:
              course_results.append({'ticketid': ticket['ticketid'], 'org': lms_output[0], 'tickinfo': ticket, 'mode': lms_user_output[0]})
            else:
              course_results.append({'ticketid': ticket['ticketid'], 'org': lms_output[0], 'tickinfo': ticket})    
        else:
          edge_cur.execute(course_org_sql + ticket['course'] + "'")
          edge_output = edge_cur.fetchone()
          if edge_output:
            if ticket['tickobj'].requester.email:
              edge_cur.execute(user_mode_sql + ticket['tickobj'].requester.email + "' and sc.course_id = '" + ticket['course'] + "'")
              edge_user_output = edge_cur.fetchone()
              if edge_user_output:
                course_results.append({'ticketid': ticket['ticketid'], 'org': edge_output[0], 'tickinfo': ticket, 'mode': edge_user_output[0]})
              else:  
                course_results.append({'ticketid': ticket['ticketid'], 'org': edge_output[0], 'tickinfo': ticket})
          else:  
            no_course_results.append({'ticketid': ticket['ticketid'], 'org': 'no course no org', 'tickinfo': ticket})
      except (pymysql.err.ProgrammingError, UnicodeEncodeError):
        bad_course_results.append({'ticketid': ticket['ticketid'], 'org': 'bad course id', 'tickinfo': ticket})     
  lms_cur.close()
  edge_cur.close()
  return course_results, no_course_results, bad_course_results

# Adds the org tag as 'partner_org' to the ticket
def org_tag_add(api_connection, course_results, vconn, log_file = None):
  print ('Updating Zendesk tickets......')
  program_sql = "select program_type, program_title from production.d_program_course where course_id = 'COURSEID'"
  vcur = vconn.cursor()
  for ticket in course_results:
    org = 'partner_' + ticket['org']
    output = str(ticket['ticketid']) + ' ticket will add Partner Name field of ' + ticket['org'] + ' and org tag of ' + org
    print (output)
    ticket['tickinfo']['tickobj'].tags.append(org)
    program_output = '' # initializing the variable
    # if statement as some tickets include a tag that allows us to insert the Partner name, but does not include a course ID
    if ticket['tickinfo']['course']:
      vcur.execute(program_sql.replace('COURSEID', ticket['tickinfo']['course']))
      program_output = vcur.fetchone()
    for field in ticket['tickinfo']['tickobj'].custom_fields:
      if field['id'] == 34902307: # Partner field
        field['value'] = ticket['org']
      if field['id'] == 46906748: # Program field
        if program_output:
          field['value'] = program_output[0]
          #logging(log_file, str(ticket['ticketid']) + ' ticket will add Program Name of ' + program_output[0]) 
          print(str(ticket['ticketid']) + ' ticket will add Program Name of ' + program_output[0])
      if field['id'] == 61030567: # Program Title field
        if program_output:
          field['value'] = program_output[1]
          try:
            #logging(log_file, str(ticket['ticketid']) + ' ticket will add Program Title of ' + program_output[1])
            print(str(ticket['ticketid']) + ' ticket will add Program Title of ' + program_output[1])
          except:
            #logging(log_file, str(ticket['ticketid']) + ' ticket will add a UnicodeError Program Title')   
            print(str(ticket['ticketid']) + ' ticket will add a UnicodeError Program Title') 
      if field['id'] == 50703667: # Enrollment field
          if field['value']: #checking if it exists and adding tag for verified
            if field['value'] == 'verified':
              ticket['tickinfo']['tickobj'].tags.append('verified_enrollment')
          else:  
            if 'mode' in ticket.keys():
              field['value'] = ticket['mode']
              if ticket['mode'] == 'verified':
                ticket['tickinfo']['tickobj'].tags.append('verified_enrollment')
              #logging(log_file, str(ticket['ticketid']) + ' ticket will add Enrollment mode of ' + ticket['mode'])  
              print(str(ticket['ticketid']) + ' ticket will add Enrollment mode of ' + ticket['mode'])
    api_connection.tickets.update(ticket['tickinfo']['tickobj'])
    #logging(log_file, output)
    #print(output)
  vcur.close() 
  
"""
# logging function
def logging(log_file, log_string):
  log_file.write(log_string + '\n')
"""  

def main():

  timestring = time.asctime(time.localtime())
  timehour = time.localtime()
  
  #log_file = open(JENKINS LOG FILE, 'a')
  #logging(log_file, 'The current run started on: ' + timestring + '\n')
  
  # API connection info
  email = os.environ['ZENDESK_EMAIL']
  token = os.environ['ZENDESK_TOKEN']
  subdomain = 'edxsupport' #prod subdomain
  
  # zenpy required dictionary for the connection
  creds = {'email': email, 'token': token, 'subdomain': subdomain}
  
  # connection object used to search, do updates, etc
  print ('Creating Zendesk Connection object')
  api_connection = zenpy.Zenpy(**creds)
  
  # LMS DB
  hostname = os.environ['LMS_HOST']
  portnumber = 3306
  username = os.environ['LMS_USER']
  password = os.environ['LMS_PASSWORD']
  database = os.environ['LMS_DBNAME']
  
  # Edge DB
  edgehostname = os.environ['EDGE_HOST']
  edgeuser = os.environ['EDGE_USER']
  edgepw = os.environ['EDGE_PASSWORD']
  edgedb = os.environ['EDGE_DBNAME']
  
  # Data warehouse connection info
  warehousehost = os.environ['WAREHOUSE_HOST'] 
  warehouseport = 5433
  warehouseuser = os.environ['WAREHOUSE_USER'] 
  warehousepw = os.environ['WAREHOUSE_PASSWORD'] 
  warehousedb = 'warehouse'
  
  lms_conn = pymysql.connect(host = hostname, port = portnumber, user = username, passwd = password, db = database)
  enterprise_ticket_search(api_connection, lms_conn)
  lms_conn.close()
  
  tickets = ticket_search(api_connection)
  if tickets:
    lms_conn = pymysql.connect(host = hostname, port = portnumber, user = username, passwd = password, db = database)
    edge_conn = pymysql.connect(host = edgehostname, port = portnumber, user = edgeuser, passwd = edgepw, db = edgedb)
    course_output = course_search(tickets, lms_conn, edge_conn)
    lms_conn.close()
    edge_conn.close()
    whconn = {'host': warehousehost, 'port': warehouseport, 'user': warehouseuser, 'password': warehousepw, 'database': warehousedb}
    vconn = vertica_python.connect(**whconn)
    org_tag_add(api_connection, course_output[0], vconn)
    vconn.close()
    no_exist = {}
    bad_exist = {}
    
    # Organizing the tickets with bad course IDs -- this is not needed for actually adding the tags to tickets
    for noticket in course_output[1]:
      if noticket['tickinfo']['tickobj'].assignee and noticket['tickinfo']['tickobj'].status == 'solved':
        if noticket['tickinfo']['tickobj'].assignee.name in no_exist:
          no_exist[noticket['tickinfo']['tickobj'].assignee.name].append('Ticket ' + str(noticket['ticketid']) + ' has course field as ' + noticket['tickinfo']['course'])
        else:
          no_exist[noticket['tickinfo']['tickobj'].assignee.name] = ['Ticket ' + str(noticket['ticketid']) + ' has course field as ' + noticket['tickinfo']['course']]
        #print (noticket['tickinfo']['tickobj'].assignee.name + '. Ticket ' + str(noticket['ticketid']) + ' has course field as ' + noticket['tickinfo']['course'])
    for badticket in course_output[2]:
      if badticket['tickinfo']['tickobj'].assignee and badticket['tickinfo']['tickobj'].status == 'solved':
        if badticket['tickinfo']['tickobj'].assignee.name in bad_exist:
          bad_exist[badticket['tickinfo']['tickobj'].assignee.name].append('Ticket ' + str(badticket['ticketid']) + ' has course field as ' + badticket['tickinfo']['course'])
        else:
          bad_exist[badticket['tickinfo']['tickobj'].assignee.name] = ['Ticket ' + str(badticket['ticketid']) + ' has course field as ' + badticket['tickinfo']['course']]  

    """      
    # Simply printing out the tickets with bad course IDs
    for a in no_exist.items():
      print (a[0])
      for c in a[1]:
        print (c)
    for b in bad_exist.items():
      print (b[0])
      for d in b[1]:
        print (d)   
   
    if no_exist:
      #timehour = time.localtime()
      if timehour.tm_hour == 15:
        message = "Below are all the course IDs within the Zendesk course field that do not exist in the edX or Edge databases.\n\n"
        receivers = [email, email]
        #receivers = [email]
        for name in no_exist.items():
          message = message + name[0] + "\n"
          for nameticket in name[1]:
            message = message + nameticket + "\n"
          message = message + "\n"
        send_email(receivers, message)
    """    
        
  else:
    print ("All tickets either have a blank or 'none' course field")    
  
  #logging(log_file, '\n')
  #log_file.close()

# This is the standard boilerplate that calls the main() function
if __name__ == '__main__':
  main()
