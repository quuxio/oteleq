"""Defect controls for the fixed prepared-worker acceptance checker."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from google.protobuf.json_format import MessageToDict
from google.protobuf.message import DecodeError
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
import check_worker

ORIGINAL=Path(__file__).resolve().parent/'worker-v3'


class WorkerChecks(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(prefix='oteleq-worker-oracle-')
        self.addCleanup(temporary.cleanup)
        self.folder=Path(temporary.name)/'capture'
        shutil.copytree(ORIGINAL,self.folder)

    def check(self):
        return check_worker.check(self.folder,source_root=ORIGINAL)

    def refuses(self):
        with self.assertRaises((AssertionError,DecodeError)):
            self.check()

    def test_complete_fixed_graph_and_telemetry_pass_but_stderr_difference_remains_visible(self):
        result=self.check()
        self.assertEqual(result['selected_spans'],1)
        self.assertEqual(result['verdict'],'different_observed')

    def test_equal_wrong_receiver_and_static_values_refuse(self):
        for lane in ('baseline','instrumented'):
            p=self.folder/lane/'observation'
            value=json.loads(p.read_text())
            value['after']['nodes'][0]['fields']['value']['value']='14'
            value['outcome']['value']['roots']['result']['value']='14'
            p.write_text(json.dumps(value))
        self.refuses()

    def test_stale_source_identity_and_extra_application_stderr_refuse(self):
        path=self.folder/'instrumented/launch.json'
        value=json.loads(path.read_text())
        value['application']['sources'][0]['sha256']='0'*64
        path.write_text(json.dumps(value))
        self.refuses()
        shutil.copyfile(ORIGINAL/'instrumented/launch.json',path)
        with (self.folder/'instrumented/application/stderr').open('a') as stream:stream.write('Unexpected app output\n')
        self.refuses()

    def test_raw_protobuf_and_forged_decoded_counters_refuse(self):
        manifest=json.loads((self.folder/'http-capture.json').read_text())
        row=next(row for row in manifest['bodies'] if row['path']=='/v1/metrics')
        path=self.folder/row['file'];original=path.read_bytes()
        path.write_bytes(original+b'\x80')
        self.refuses()
        message=ExportMetricsServiceRequest();message.ParseFromString(original)
        for resource in message.resource_metrics:
            for scope in resource.scope_metrics:
                for metric in scope.metrics:
                    if metric.name=='otelc.function.calls':
                        metric.sum.data_points[0].as_int=2
        path.write_bytes(message.SerializeToString())
        cache=self.folder/'decoded-otlp.json';decoded=json.loads(cache.read_text())
        index=manifest['bodies'].index(row)
        decoded[index]['message']=MessageToDict(message,preserving_proto_field_name=True)
        cache.write_text(json.dumps(decoded))
        self.refuses()


if __name__=='__main__':unittest.main()
