# -*- coding: utf-8 -*-

from collections import OrderedDict

import parsedmarc
from elasticsearch_dsl.search import Q
from elasticsearch_dsl import connections, Object, DocType, Index, Nested, \
    InnerDoc, Integer, Text, Boolean, DateRange, Ip, Date

aggregate_index = Index("dmarc_aggregate")
forensic_index = Index("dmarc_forensic")


class PolicyOverride(InnerDoc):
    type = Text()
    comment = Text()


class PublishedPolicy(InnerDoc):
    adkim = Text()
    aspf = Text()
    p = Text()
    sp = Text()
    pct = Integer()
    fo = Integer()


class DKIMResult(InnerDoc):
    domain = Text()
    selector = Text()
    result = Text()


class SPFResult(InnerDoc):
    domain = Text()
    scope = Text()
    results = Text()


class AggregateReportDoc(DocType):
    class Meta:
        index = "dmarc_aggregate"

    xml_schema = Text()
    org_name = Text()
    org_email = Text()
    org_extra_contact_info = Text()
    report_id = Text()
    date_range = DateRange()
    errors = Text()
    domain = Text()
    published_policy = Object(PublishedPolicy)
    source_ip_address = Ip()
    source_country = Text()
    source_reverse_dns = Text()
    source_Base_domain = Text()
    message_count = Integer
    disposition = Text()
    dkim_aligned = Boolean()
    spf_aligned = Boolean()
    passed_dmarc = Boolean()
    policy_overrides = Nested(PolicyOverride)
    header_from = Text()
    envelope_from = Text()
    envelope_to = Text()
    dkim_results = Nested(DKIMResult)
    spf_results = Nested(SPFResult)

    def add_policy_override(self, type_, comment):
        self.policy_overrides.append(PolicyOverride(type=type_,
                                                    comment=comment))

    def add_dkim_result(self, domain, selector, result):
        self.dkim_results.append(DKIMResult(domain=domain,
                                            selector=selector,
                                            result=result))

    def add_spf_result(self, domain, scope, result):
        self.spf_results.append(SPFResult(domain=domain,
                                          scope=scope,
                                          result=result))

    def save(self, ** kwargs):
        self.passed_dmarc = False
        self.passed_dmarc = self.spf_aligned or self.dkim_aligned
        return super().save(** kwargs)


class EmailAddressDoc(InnerDoc):
    display_name = Text()
    address = Text()


class EmailAttachmentDoc(DocType):
    filename = Text()
    content_type = Text()


class ForensicSampleDoc(InnerDoc):
    raw = Text()
    headers = Object()
    headers_only = Boolean()
    to = Nested(EmailAddressDoc)
    subject = Text()
    filename_safe_subject = Text()
    _from = Object(EmailAddressDoc)
    date = Date()
    reply_to = Nested(EmailAddressDoc)
    cc = Nested(EmailAddressDoc)
    bcc = Nested(EmailAddressDoc)
    body = Text()
    attachments = Nested(EmailAttachmentDoc)

    def add_to(self, display_name, address):
        self.to.append(EmailAddressDoc(display_name=display_name,
                                       address=address))

    def add_reply_to(self, display_name, address):
        self.reply_to.append(EmailAddressDoc(display_name=display_name,
                                             address=address))

    def add_cc(self, display_name, address):
        self.cc.append(EmailAddressDoc(display_name=display_name,
                                       address=address))

    def add_bcc(self, display_name, address):
        self.bcc.append(EmailAddressDoc(display_name=display_name,
                                        address=address))

    def add_attachment(self, filename, content_type):
        self.attachments.append(filename=filename,
                                content_type=content_type)


class ForensicReportDoc(DocType):
    class Meta:
        index = "dmarc_forensic"

    feedback_type = Text()
    user_agent = Text()
    version = Text()
    original_mail_from = Text()
    arrival_date = Date()
    domain = Text()
    original_envelope_id = Text()
    authentication_results = Text()
    delivery_results = Text()
    source_ip_address = Ip()
    source_country = Text()
    source_reverse_dns = Text()
    source_authentication_mechanisms = Text()
    source_auth_failures = Text()
    dkim_domain = Text()
    original_rcpt_to = Text()
    sample = Object(ForensicSampleDoc)


class AlreadySaved(RuntimeError):
    """Raised when a report to be saved matches an existing report"""


def set_hosts(hosts):
    """
    Sets the Elasticsearch hosts to use

    Args:
        hosts: A single hostname or URL, or list of hostnames or URLs
    """
    if type(hosts) != list:
        hosts = [hosts]
    connections.create_connection(hosts=hosts, timeout=20)


def create_indexes():
    """Creates the required indexes"""
    if not aggregate_index.exists():
        aggregate_index.create()
    if not forensic_index.exists():
        forensic_index.create()


def save_aggregate_report_to_elasticsearch(aggregate_report):
    """
    Saves a parsed DMARC aggregate report to ElasticSearch
    
    Args:
        aggregate_report (OrderedDict): A parsed forensic report

    Raises:
        AlreadySaved

    """
    aggregate_report = aggregate_report.copy()
    metadata = aggregate_report["report_metadata"]
    org_name = metadata["org_name"]
    report_id = metadata["report_id"]
    domain = aggregate_report["policy_published"]["domain"]

    org_name_query = Q(dict(match=dict(org_name=org_name)))
    report_id_query = Q(dict(match=dict(report_id=report_id)))
    domain_query = Q(dict(match=dict(domain=domain)))

    search = aggregate_index.search()
    search.query = org_name_query & report_id_query & domain_query
    existing = search.execute()
    if len(existing) > 0:
        raise AlreadySaved("Aggregate report ID {0} from {1} about {2} "
                           "already exists in Elasticsearch".format(report_id,
                                                                    org_name,
                                                                    domain))

    aggregate_report["begin_date"] = parsedmarc.human_timestamp_to_datetime(
        metadata["begin_date"])
    aggregate_report["end_date"] = parsedmarc.human_timestamp_to_datetime(
        metadata["end_date"])
    date_range = (aggregate_report["begin_date"],
                  aggregate_report["end_date"])
    published_policy = PublishedPolicy(
        adkim=aggregate_report["policy_published"]["adkim"],
        aspf=aggregate_report["policy_published"]["aspf"],
        p=aggregate_report["policy_published"]["p"],
        sp=aggregate_report["policy_published"]["sp"],
        pct=aggregate_report["policy_published"]["pct"],
        fo=aggregate_report["policy_published"]["fo"]
    )

    for record in aggregate_report["records"]:
        agg_doc = AggregateReportDoc(
            xml_schemea=aggregate_report["xml_schema"],
            org_name=metadata["org_name"],
            org_email=metadata["org_email"],
            org_extra_contact_info=metadata["org_extra_contact_info"],
            report_id=metadata["report_id"],
            date_range=date_range,
            errors=metadata["errors"],
            domain=aggregate_report["policy_published"]["domain"],
            published_policy=published_policy,
            source_ip_address=record["source"]["ip_address"],
            source_country=record["source"]["country"],
            source_reverse_dns=record["source"]["reverse_dns"],
            source_base_domain=record["source"]["base_domain"],
            message_count=record["count"],
            disposition=record["policy_evaluated"]["disposition"],
            dkim_aligned=record["policy_evaluated"]["dkim"] == "pass",
            spf_aligned=record["policy_evaluated"]["spf"] == "pass",
            header_from=record["identifiers"]["header_from"],
            envelope_from=record["identifiers"]["envelope_from"],
            envelope_to=record["identifiers"]["envelope_to"]
        )

        for override in record["policy_evaluated"]["policy_override_reasons"]:
            agg_doc.add_policy_override(type_=override["type"],
                                        comment=override["comment"])

        for dkim_result in record["auth_results"]["dkim"]:
            agg_doc.add_dkim_result(domain=dkim_result["domain"],
                                    selector=dkim_result["selector"],
                                    result=dkim_result["result"])

        for spf_result in record["auth_results"]["spf"]:
            agg_doc.add_spf_result(domain=spf_result["domain"],
                                   scope=spf_result["scope"],
                                   result=spf_result["result"])
        agg_doc.save()


def save_forensic_report_to_elasticsearch(forensic_report):
    """
        Saves a parsed DMARC forensic report to ElasticSearch

        Args:
            forensic_report (OrderedDict): A parsed forensic report

        Raises:
            AlreadySaved

        """
    forensic_report = forensic_report.copy()
    sample_date = forensic_report["parsed_sample"]["date"]
    sample_date = parsedmarc.human_timestamp_to_datetime(sample_date)
    original_headers = forensic_report["parsed_sample"]["headers"]
    headers = OrderedDict()
    for original_header in original_headers:
        headers[original_header.lower()] = original_headers[original_header]

    arrival_date_human = forensic_report["arrival_date_utc"]
    arrival_date = parsedmarc.human_timestamp_to_datetime(arrival_date_human)

    search = forensic_index.search()
    to_query = {"match": {"sample.headers.to": headers["to"]}}
    from_query = {"match": {"sample.headers.from": headers["from"]}}
    subject_query = {"match": {"sample.headers.subject": headers["subject"]}}
    search.query = Q(to_query) & Q(from_query) & Q(subject_query)
    existing = search.execute()

    if len(existing) > 0:
        raise AlreadySaved("A matching forensic sample to {0} from {1} "
                           "with a subject of {2} and arrival date of {3} "
                           "already exists in "
                           "Elasticsearch".format(headers["to"],
                                                  headers["from"],
                                                  headers["subject"],
                                                  arrival_date_human
                                                  ))

    parsed_sample = forensic_report["parsed_sample"]
    sample = ForensicSampleDoc(
        raw=forensic_report["sample"],
        headers=headers,
        headers_only=forensic_report["sample_headers_only"],
        date=sample_date,
        subject=forensic_report["parsed_sample"]["subject"],
        filename_safe_subject=parsed_sample["filename_safe_subject"],
        body=forensic_report["parsed_sample"]["body"]
    )

    for address in forensic_report["parsed_sample"]["to"]:
        sample.add_to(display_name=address["display_name"],
                      address=address["address"])
    for address in forensic_report["parsed_sample"]["reply_to"]:
        sample.add_reply_to(display_name=address["display_name"],
                            address=address["address"])
    for address in forensic_report["parsed_sample"]["cc"]:
        sample.add_cc(display_name=address["display_name"],
                      address=address["address"])
    for address in forensic_report["parsed_sample"]["bcc"]:
        sample.add_bcc(display_name=address["display_name"],
                       address=address["address"])
    for attachment in forensic_report["parsed_sample"]["attachments"]:
        sample.add_attachment(filename=attachment["filename"],
                              content_type=attachment["mail_content_type"])

    forensic_doc = ForensicReportDoc(
        feedback_type=forensic_report["feedback_type"],
        user_agent=forensic_report["user_agent"],
        version=forensic_report["version"],
        original_mail_from=forensic_report["original_mail_from"],
        arrival_date=arrival_date,
        domain=forensic_report["reported_domain"],
        original_envelope_id=forensic_report["original_envelope_id"],
        authentication_results=forensic_report["authentication_results"],
        delivery_results=forensic_report["delivery_result"],
        source_ip_address=forensic_report["source"]["ip_address"],
        source_country=forensic_report["source"]["country"],
        source_reverse_dns=forensic_report["source"]["reverse_dns"],
        source_base_domain=forensic_report["source"]["base_domain"],
        authentication_mechanisms=forensic_report["authentication_mechanisms"],
        auth_failure=forensic_report["auth_failure"],
        dkim_domain=forensic_report["dkim_domain"],
        original_rcpt_to=forensic_report["original_rcpt_to"],
        sample=sample
    )

    forensic_doc.save()