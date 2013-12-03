import fixtures
from vnc_api.vnc_api import *
from util import retry
from time import sleep
from tcutils.services import get_status

class SvcInstanceFixture(fixtures.Fixture):
    def __init__(self, connections, inputs, domain_name, project_name, si_name,
                 svc_template, if_list, left_vn_name=None, right_vn_name=None, do_verify=True, max_inst= 1):
        self.vnc_lib = connections.vnc_lib 
        self.api_s_inspect = connections.api_server_inspect
        self.nova_fixture = connections.nova_fixture
        self.inputs= connections.inputs
        self.domain_name = domain_name
        self.project_name = project_name
        self.si_name = si_name
        self.svc_template = svc_template
        self.st_name = svc_template.name
        self.si_obj = None
        self.domain_fq_name = [self.domain_name]
        self.project_fq_name = [self.domain_name, self.project_name]
        self.si_fq_name = [self.domain_name, self.project_name, self.si_name]
        self.logger = inputs.logger
        self.left_vn_name = left_vn_name
        self.right_vn_name = right_vn_name
        self.do_verify = do_verify
        self.if_list = if_list
        self.max_inst= max_inst
        self.si = None
        self.svm_ids = []
        self.cs_svc_vns = []
        self.cs_svc_ris = []
        self.svn_list = ['svc-vn-mgmt', 'svc-vn-left', 'svc-vn-right']
    #end __init__

    def setUp(self):
        super(SvcInstanceFixture, self).setUp()
        self.si_obj = self._create_si()
    #end setUp

    def cleanUp(self):
        super(SvcInstanceFixture, self).cleanUp()
        self._delete_si()
        assert self.verify_on_cleanup()
    #end cleanUp

    def _create_si(self):
        self.logger.debug("Creating service instance: %s", self.si_fq_name)
        try:
            svc_instance = self.vnc_lib.service_instance_read(fq_name = self.si_fq_name)
            self.logger.debug("Service instance: %s already exists", self.si_fq_name)
        except NoIdError:
            project = self.vnc_lib.project_read(fq_name = self.project_fq_name)
            svc_instance = ServiceInstance(self.si_name, parent_obj = project)
            if self.left_vn_name and self.right_vn_name:
                si_prop = ServiceInstanceType(left_virtual_network=self.left_vn_name,
                                              right_virtual_network=self.right_vn_name)
            else:
                si_prop = ServiceInstanceType()
            si_prop.set_scale_out(ServiceScaleOutType(self.max_inst))
            svc_instance.set_service_instance_properties(si_prop)
            svc_instance.set_service_template(self.svc_template)
            self.vnc_lib.service_instance_create(svc_instance)
            svc_instance = self.vnc_lib.service_instance_read(fq_name = self.si_fq_name)
        return svc_instance
    #end _create_si

    def _delete_si(self):
        self.logger.debug("Deleting service instance: %s", self.si_fq_name)
        self.vnc_lib.service_instance_delete(fq_name = self.si_fq_name)
    #end _delete_si

    def verify_si(self):
        """check service instance"""
        self.project = self.vnc_lib.project_read(fq_name=self.project_fq_name)
        try:
            self.si = self.vnc_lib.service_instance_read(fq_name = self.si_fq_name)
            self.logger.debug("Service instance: %s created succesfully", self.si_fq_name)
        except NoIdError:
            errmsg = "Service instance: %s not found." % self.si_fq_name
            self.logger.warn(errmsg)
            return (False, errmsg)
        return True, None

    def verify_st(self):
        """check service template"""
        self.cs_si = self.api_s_inspect.get_cs_si(si=self.si_name, refresh=True) 
        st_refs = self.cs_si['service-instance']['service_template_refs']
        if not st_refs:
            errmsg = "No service template refs in SI '%s'" %  self.si_name
            self.logger.warn(errmsg)
            return (False, errmsg)

        st_ref_name = [st_ref['to'][-1] for st_ref in st_refs if st_ref['to'][-1] == self.st_name]
        if not st_ref_name:
            errmsg = "SI '%s' has no service template ref to %s" % (self.si_name, self.st_name)
            self.logger.warn(errmsg)
            return (False, errmsg)
        self.logger.debug("SI '%s' has service template ref to %s", self.si_name, self.st_name)

        return True, None

    def verify_svm(self):
        """check Service VM"""
        self.vm_refs = self.cs_si['service-instance']['virtual_machine_back_refs']
        if not self.vm_refs:
            errmsg = "SI %s dosent have back refs to Service VM" % self.si_name
            self.logger.warn(errmsg)
            return (False, errmsg)

        self.logger.debug("SI %s has back refs to Service VM", self.si_name)
        self.svm_ids = [vm_ref['to'][0] for vm_ref in self.vm_refs]
        for svm_id in self.svm_ids:
            cs_svm = self.api_s_inspect.get_cs_vm(vm_id=svm_id, refresh=True)
            if not cs_svm:
                errmsg = "Service VM for SI '%s' not launched" % self.si_name
                self.logger.warn(errmsg)
                #self.logger.debug("Service monitor status: %s", get_status('contrail-svc-monitor'))
                return (False, errmsg)
        self.logger.debug("Serivce VM for SI '%s' is launched", self.si_name)
        return True, None

    def svm_compute_node_ip(self):
        admin_project_uuid = self.api_s_inspect.get_cs_project()['project']['uuid']
        svm_name = self.si_name + str ('_1')
        svm_obj = self.nova_fixture.get_vm_if_present(svm_name, admin_project_uuid)
        svm_compute_node_ip = self.inputs.host_data[self.nova_fixture.get_nova_host_of_vm(svm_obj)]['host_ip']
        return svm_compute_node_ip


    def verify_interface_props(self):
        """check if properties"""
        vm_if_props = self.svc_vm_if['virtual-machine-interface']['virtual_machine_interface_properties']
        if not vm_if_props:
            errmsg = "No VM interface in Service VM of SI %s" % self.si_name
            self.logger.warn(errmsg)
            return (False, errmsg)
        self.logger.debug("VM interface present in Service VM of SI %s", self.si_name)

        self.if_type = vm_if_props['service_interface_type']
        if (not self.if_type and self.if_type not in self.if_list):
            errmsg = "Interface type '%s' is not present in Servcice VM of SI '%s'" % (self.if_type, self.si_name)
            self.logger.warn(errmsg)
            return (False, errmsg)
        self.logger.debug("Interface type '%s' is present in Service VM of SI '%s'", self.if_type, self.si_name)
        return True, None
       

    def verify_vn_links(self):
        """check vn links"""
        vn_refs = self.svc_vm_if['virtual-machine-interface']['virtual_network_refs']
        if not vn_refs:
            errmsg = "IF %s has no back refs to  vn" % self.if_type
            self.logger.warn(errmsg)
            return (False, errmsg)
        self.logger.debug("IF %s has back refs to  vn", self.if_type)
        for vn in vn_refs:
            self.svc_vn = self.api_s_inspect.get_cs_vn(vn=vn['to'][-1], refresh=True)
            if self.svc_vn['virtual-network']['name'] in self.svn_list:
                self.cs_svc_vns.append(vn['to'][-1])
            if not self.svc_vn:
                errmsg = "IF %s has no vn" % self.if_type
                self.logger.warn(errmsg)
                return (False, errmsg)
            self.logger.debug("IF %s has vn '%s'", self.if_type, self.svc_vn['virtual-network']['name'])
        return True, None

    @retry(delay=1, tries=5)
    def verify_ri(self):
        """check routing instance"""
        ri_refs = self.svc_vm_if['virtual-machine-interface']['routing_instance_refs']
        vn_name = self.svc_vn['virtual-network']['name']
        if not ri_refs:
            errmsg = "IF %s, VN %s has no back refs to routing instance" % (self.if_type, vn_name)
            self.logger.warn(errmsg)
            return (False, errmsg)
        self.logger.debug("IF %s, VN %s has back refs to routing instance", self.if_type, vn_name)

        for ri in ri_refs:
            svc_ri = self.api_s_inspect.get_cs_ri_by_id(ri['uuid'])
            if svc_ri['routing-instance']['name'] in self.svn_list:
                self.cs_svc_ris.append(ri['uuid'])
            if not svc_ri:
                errmsg = "IF %s VN %s has no RI" % (self.if_type, vn_name)
                self.logger.warn(errmsg)
                return (False, errmsg)
            ri_name = svc_ri['routing-instance']['name']
            self.logger.debug ("IF %s VN %s has RI", self.if_type, vn_name)
            if ri_name == vn_name:
                continue
            else:
                if not ri['attr']:
                    errmsg = "IF %s VN %s RI %s no attributes" % (self.if_type, vn_name, ri_name)
                    self.logger.warn(errmsg)
                    return (False, errmsg)
                self.logger.debug("IF %s VN %s RI %s has attributes", self.if_type, vn_name, ri_name)
                #check service chain
                sc_info = svc_ri['routing-instance']['service_chain_information']
                if not sc_info:
                    errmsg = "IF %s VN %s RI %s has no SCINFO" % (self.if_type, vn_name, ri_name)
                    self.logger.warn(errmsg)
                    return (False, errmsg)
                self.logger.debug("IF %s VN %s RI %s has SCINFO", self.if_type, vn_name, ri_name)
        return True, None

    def verify_svm_interface(self):
        #check VM interfaces
        for svm_id in self.svm_ids:
            cs_svm = self.api_s_inspect.get_cs_vm(vm_id=svm_id, refresh=True)
            svm_ifs = cs_svm['virtual-machine']['virtual_machine_interfaces']
        if len(svm_ifs) != len(self.if_list):
            errmsg = "Service VM dosen't have all the interfaces %s" % self.if_list
            self.logger.warn(errmsg)
            return False, errmsg

        svc_vm_if = self.api_s_inspect.get_cs_vmi_of_vm(svm_ifs[0]['to'][0], refresh=True)
        for self.svc_vm_if in svc_vm_if:
            result, msg = self.verify_interface_props()
            if not result:
                return result, msg

            result, msg = self.verify_vn_links()
            if not result:
                return result, msg

            result, msg = self.verify_ri()
            if not result:
                return result, msg
        return True, None

    def verify_on_setup(self):
        self.report(self.verify_si())
        self.report(self.verify_st())
        self.report(self.verify_svm())
        self.report(self.verify_svm_interface())
        return True, None
    #end verify_on_setup

    def report(self, result):
        if type(result) is tuple:
            result, errmsg = result
        if not result: 
            assert False, errmsg

    @retry(delay=2, tries=15)
    def verify_si_not_in_api_server(self):
        if not self.si:
            return True, None
        si = self.api_s_inspect.get_cs_si(si=self.si_name, refresh=True)
        if si:
            errmsg = "Service instance %s not removed from api server" % self.si_name
            self.logger.warn(errmsg)
            return False, errmsg
        self.logger.debug("Service instance %s removed from api server" % self.si_name)
        return True, None

    @retry(delay=5, tries=12)
    def verify_svm_not_in_api_server(self):
        for svm_id in self.svm_ids:
            cs_svm = self.api_s_inspect.get_cs_vm(vm_id=svm_id, refresh=True)
            if cs_svm:
                errmsg = "Service VM for SI '%s' not deleted" % self.si_name
                self.logger.warn(errmsg)
                return (False, errmsg)
        self.logger.debug("Serivce VM for SI '%s' is deleted", self.si_name)
        return True, None

    def si_exists(self):
        svc_instances = self.vnc_lib.service_instances_list()['service-instances']
        if len(svc_instances) == 0:
            return False
        return True

    @retry(delay=2, tries=15)
    def verify_svn_not_in_api_server(self):
        if self.si_exists():
            self.logger.info("Some Service Instance exists; skip SVN check in API server")
            return True, None
        for vn in self.cs_svc_vns:
            svc_vn = self.api_s_inspect.get_cs_vn(vn=vn, refresh=True)
            if svc_vn:
                errmsg = "Service VN %s is not removed from api server" % vn
                self.logger.warn(errmsg)
                return (False, errmsg)
            self.logger.debug("Service VN %s is removed from api server", vn)
        return True, None
          
    @retry(delay=2, tries=15)
    def verify_ri_not_in_api_server(self):
        if self.si_exists():
            self.logger.info("Some Service Instance exists; skip RI check in API server")
            return True, None
        for ri in self.cs_svc_ris:
            svc_ri = self.api_s_inspect.get_cs_ri_by_id(ri)
            if svc_ri:
                errmsg = "RI %s is not removed from api server" % ri
                self.logger.warn(errmsg)
                return (False, errmsg)
            self.logger.debug ("RI %s is removed from api server", ri)
        return True, None

    def verify_on_cleanup(self):
        result = True
        result, msg = self.verify_si_not_in_api_server()
        assert result, msg
        result, msg = self.verify_svm_not_in_api_server()
        assert result, msg
        if self.do_verify:
            result, msg = self.verify_svn_not_in_api_server()
            assert result, msg
            result, msg = self.verify_ri_not_in_api_server()
            assert result, msg

        return result
    #end verify_on_cleanup
    
#end SvcInstanceFixture
